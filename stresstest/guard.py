"""
Safety checks for stress-test mode. STRESS-TEST BRANCH ONLY: never merge into main.

Stress-test mode signs everyone in automatically as fake users. That is only
acceptable on a private test server holding generated data, so the app
refuses to start in this mode if anything points at the real world:
Microsoft 365 credentials, or a way to send or read email.
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

FAKE_USER_PREFIX = "stress-"
FAKE_EMAIL_DOMAIN = "example.invalid"


def check(*, entra_values: list[str], inbound_email: str) -> None:
    """Raise if stress-test mode is combined with real connections."""
    if any(v.strip() for v in entra_values):
        raise ImproperlyConfigured(
            "STRESS_TEST_MODE is on but ENTRA_TENANT_ID / ENTRA_CLIENT_ID / "
            "ENTRA_CLIENT_SECRET are set. The stress-test server must have no "
            "Microsoft 365 credentials: remove them from .env."
        )
    if inbound_email.strip().lower() not in ("", "off"):
        raise ImproperlyConfigured(
            "STRESS_TEST_MODE is on but INBOUND_EMAIL isn't 'off'. "
            "The stress-test server must not read any mailbox."
        )
