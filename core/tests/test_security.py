"""
Production security settings: the HTTPS redirect, HSTS, and the health check.

These load config/settings.py afresh with a production-like environment (and
no .env file), then send requests through the real middleware with those
settings, so they test what the server will actually do.
"""

import os
import runpy
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings

SETTINGS_FILE = Path(settings.BASE_DIR) / "config" / "settings.py"
HOST = "helpdesk.mckennalabs.com"

PRODUCTION_ENV = {
    "DJANGO_SECRET_KEY": "test-only-not-a-real-secret",
    "DJANGO_DEBUG": "False",
    "DJANGO_ALLOWED_HOSTS": HOST,
    "DJANGO_CSRF_TRUSTED_ORIGINS": f"https://{HOST}",
}

# The settings the security middleware and host checks read.
SECURITY_SETTINGS = (
    "ALLOWED_HOSTS",
    "SECURE_SSL_REDIRECT",
    "SECURE_REDIRECT_EXEMPT",
    "SECURE_PROXY_SSL_HEADER",
    "SECURE_HSTS_SECONDS",
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    "SECURE_HSTS_PRELOAD",
)


def load_settings(**env) -> dict:
    """Run config/settings.py with PRODUCTION_ENV plus `env`, ignoring .env."""
    with mock.patch.dict(os.environ), mock.patch("dotenv.load_dotenv"):
        for name in [n for n in os.environ if n.startswith("DJANGO_")]:
            del os.environ[name]
        os.environ.update({**PRODUCTION_ENV, **env})
        return runpy.run_path(str(SETTINGS_FILE))


def production_settings(**env):
    """override_settings() with the security settings the server would get."""
    loaded = load_settings(**env)
    return override_settings(**{name: loaded[name] for name in SECURITY_SETTINGS})


class ProductionSettingsTests(TestCase):
    def test_secure_by_default_when_debug_is_off(self):
        s = load_settings()
        self.assertIs(s["SECURE_SSL_REDIRECT"], True)
        self.assertEqual(s["SECURE_REDIRECT_EXEMPT"], [r"^healthz$"])
        self.assertEqual(s["SECURE_PROXY_SSL_HEADER"], ("HTTP_X_FORWARDED_PROTO", "https"))
        self.assertEqual(s["SECURE_HSTS_SECONDS"], 31_536_000)
        self.assertIs(s["SECURE_HSTS_INCLUDE_SUBDOMAINS"], True)
        self.assertIs(s["SESSION_COOKIE_SECURE"], True)
        self.assertIs(s["CSRF_COOKIE_SECURE"], True)
        # Docker's health check host is allowed alongside the real one.
        self.assertEqual(s["ALLOWED_HOSTS"], [HOST, "127.0.0.1"])

    def test_settings_can_be_changed_from_the_environment(self):
        s = load_settings(DJANGO_SECURE_SSL_REDIRECT="False", DJANGO_SECURE_HSTS_SECONDS="3600")
        self.assertIs(s["SECURE_SSL_REDIRECT"], False)
        self.assertEqual(s["SECURE_HSTS_SECONDS"], 3600)

    def test_blank_values_keep_the_secure_defaults(self):
        s = load_settings(DJANGO_SECURE_SSL_REDIRECT="", DJANGO_SECURE_HSTS_SECONDS="")
        self.assertIs(s["SECURE_SSL_REDIRECT"], True)
        self.assertEqual(s["SECURE_HSTS_SECONDS"], 31_536_000)

    def test_not_applied_with_debug_on(self):
        s = load_settings(DJANGO_DEBUG="True")
        self.assertNotIn("SECURE_SSL_REDIRECT", s)
        self.assertNotIn("SECURE_HSTS_SECONDS", s)
        self.assertEqual(s["ALLOWED_HOSTS"], [HOST])


class HttpsRedirectTests(TestCase):
    def test_healthz_is_not_redirected(self):
        # Exactly what Docker's HEALTHCHECK sends: plain HTTP to 127.0.0.1:8000.
        with production_settings():
            response = self.client.get("/healthz", HTTP_HOST="127.0.0.1:8000")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_other_plain_http_requests_are_redirected(self):
        with production_settings():
            response = self.client.get("/signin/?next=/queue/", HTTP_HOST=HOST)
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], f"https://{HOST}/signin/?next=/queue/")

    def test_requests_through_the_proxy_are_served_with_hsts(self):
        # The proxy says "this was HTTPS" with X-Forwarded-Proto.
        with production_settings():
            response = self.client.get(
                "/signin/", HTTP_HOST=HOST, HTTP_X_FORWARDED_PROTO="https"
            )
        self.assertEqual(response.status_code, 200)
        # The same value deploy/caddy/Caddyfile sends.
        self.assertEqual(
            response["Strict-Transport-Security"], "max-age=31536000; includeSubDomains"
        )

    def test_redirect_can_be_switched_off(self):
        with production_settings(DJANGO_SECURE_SSL_REDIRECT="off"):
            response = self.client.get("/signin/", HTTP_HOST=HOST)
        self.assertEqual(response.status_code, 200)
