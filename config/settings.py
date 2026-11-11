"""
Django settings for InH-Ticketing.

Everything that differs between your PC and the server (secrets, database,
hostnames, Entra IDs) comes from environment variables. For local development
those live in a `.env` file next to manage.py; see `.env.example`.
"""

import os
import re
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from config import __version__

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env for local development. Real environment variables win, so Docker
# or the server can override anything in the file.
load_dotenv(BASE_DIR / ".env", override=False)


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


_DEPARTMENT_KEY = re.compile(r"[a-z][a-z0-9-]{0,15}")


def env_departments(name: str) -> dict[str, str]:
    """"mechanics=a@example.com, cleaning=b@example.com" -> {"mechanics": "a@example.com", ...}

    The keys are departments' keys, as shown in the admin site (Tickets > Departments).
    IT isn't one: its mailbox is HELPDESK_MAILBOX."""
    result = {}
    for part in os.environ.get(name, "").replace(";", ",").split(","):
        key, _, value = part.partition("=")
        key, value = key.strip().lower(), value.strip()
        if not key and not value:
            continue
        if not _DEPARTMENT_KEY.fullmatch(key) or key == "it" or not value:
            raise ImproperlyConfigured(
                f"{name}: use department=address pairs, with each department's key from the admin site "
                "(Tickets > Departments), e.g. mechanics=mechanics@example.com. IT's is HELPDESK_MAILBOX."
            )
        result[key] = value
    return result


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


APP_VERSION = __version__

# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", default=False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is not set. Copy .env.example to .env and follow the "
        "instructions there to generate one."
    )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Our apps
    "accounts",
    "core",
    "tickets",
    "notifications",
    "inbound",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.PrivatePagesMiddleware",  # signed-in pages: Cache-Control private, no-store
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.app_info",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
# DATABASE_URL looks like postgres://user:password@host:5432/dbname.
# Without it we fall back to a local SQLite file, which is fine on your PC.
# (An empty DATABASE_URL= line in .env counts as "not set".)
DATABASES = {
    "default": dj_database_url.parse(
        os.environ.get("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Users and sign-in
# --------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:signin"
LOGIN_REDIRECT_URL = "core:home"

# Sign-in is Microsoft 365 only: there is no password form anywhere in the app
# (the admin login is redirected too), so there are no password validators.
# ModelBackend is still needed: it loads the signed-in user on each request.
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]

# Roles are read from Entra each time someone signs in, so a session length of
# a working day means a role change in Entra takes effect by the next day.
SESSION_COOKIE_AGE = 60 * 60 * 12  # 12 hours at most
# Signing in lasts until the browser closes (and 12 hours at most), so a
# shared PC doesn't stay signed in for the next person.
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# Entra ID (Microsoft 365) app registration. See docs/entra-setup.md.
ENTRA_TENANT_ID = os.environ.get("ENTRA_TENANT_ID", "").strip()
ENTRA_CLIENT_ID = os.environ.get("ENTRA_CLIENT_ID", "").strip()
ENTRA_CLIENT_SECRET = os.environ.get("ENTRA_CLIENT_SECRET", "").strip()
ENTRA_REDIRECT_URI = os.environ.get(
    "ENTRA_REDIRECT_URI", "http://localhost:8000/auth/callback"
).strip()
# The *values* (not display names) of the app roles defined on the registration.
ENTRA_ROLE_AGENT = os.environ.get("ENTRA_ROLE_AGENT", "Agent").strip()
ENTRA_ROLE_ADMIN = os.environ.get("ENTRA_ROLE_ADMIN", "Admin").strip()
# ENTRA_ROLE_AGENT is IT's agents. Each other department's role is set in the
# admin site (Tickets > Departments); its agents see and work only its tickets.

# --------------------------------------------------------------------------
# Internationalisation
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "America/Los_Angeles")
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Static files (CSS, icons) are served by WhiteNoise in every environment.
# --------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# The web manifest (static/icons/site.webmanifest) with its proper type.
WHITENOISE_MIMETYPES = {".webmanifest": "application/manifest+json"}

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# --------------------------------------------------------------------------
# Tickets and attachments
# --------------------------------------------------------------------------
# People see ticket #1001, #1002, ... rather than the raw database IDs.
TICKET_NUMBER_OFFSET = 1000

# Uploaded files live here. They are NOT served publicly: every download goes
# through a view that checks the person may see that ticket (and that note).
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
MEDIA_URL = "/media/"

# Resolved tickets close by themselves this many days after IT resolved them,
# unless the requester replies first. 0 turns auto-close off.
AUTO_CLOSE_RESOLVED_DAYS = int(os.environ.get("AUTO_CLOSE_RESOLVED_DAYS", "7"))
# Closed tickets are archived: read-only and out of the working views. They're
# kept this many days after that (2 years). Deleting them when the time is up
# isn't switched on yet; the ticket page shows the date.
ARCHIVE_KEEP_DAYS = int(os.environ.get("ARCHIVE_KEEP_DAYS", str(2 * 365)))

ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
ATTACHMENT_MAX_FILES = 5  # per request or reply
ATTACHMENT_EXTENSIONS = {
    # images
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".bmp",
    # documents
    ".pdf", ".txt", ".log", ".csv", ".rtf", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx", ".odt", ".ods",
    # email and archives
    ".eml", ".msg", ".zip",
}

# --------------------------------------------------------------------------
# Email notifications. See docs/email-setup.md.
# --------------------------------------------------------------------------
# The address people use to reach the app, for links in emails.
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000").rstrip("/")

# The shared mailbox emails are sent from, e.g. helpdesk-test@example.com.
HELPDESK_MAILBOX = os.environ.get("HELPDESK_MAILBOX", "").strip()
DEFAULT_FROM_EMAIL = HELPDESK_MAILBOX or "inh-ticketing@localhost"

# Who to contact when the app can't help: shown under "Can't sign in?" and on
# the error pages, e.g. "Call IT on ext. 1234, or post in IT Help in Teams."
# Blank = "Email IT at HELPDESK_MAILBOX", or "Contact IT." if that's blank too.
HELP_CONTACT = os.environ.get("HELP_CONTACT", "").strip()

# Email-in: an email that claims to be from IT only becomes a public reply if
# Exchange confirmed the sender (sent inside the organisation, or DMARC or
# composite authentication passed). Otherwise it's kept as an internal note.
# Turn off only if Exchange doesn't add those headers here (see email-setup.md).
INBOUND_VERIFY_IT_SENDERS = env_bool("INBOUND_VERIFY_IT_SENDERS", True)

# Reports (/reports/, admins only) count tickets from this date, e.g. the
# go-live date, so test and pilot tickets before it don't skew them.
# YYYY-MM-DD; blank = every ticket. Tickets whose subject starts with
# "Pilot:" (pilot feedback) are always left out.
REPORTS_FROM = os.environ.get("REPORTS_FROM", "").strip()

# Optional: where "new ticket" and unassigned-reply alerts for IT go
# (a distribution list, or a Teams channel's email address). Blank = none.
IT_NOTIFY_EMAIL = os.environ.get("IT_NOTIFY_EMAIL", "").strip()
# Each other department's alert address is set in the admin site (Tickets >
# Departments); without one, its alerts go to each of its agents.

# How emails leave the app:
#   file    - written to tmp/emails/ for you to open (default; nothing is sent)
#   console - printed in the worker's terminal
#   graph   - sent through Microsoft Graph from HELPDESK_MAILBOX
EMAIL_BACKENDS = {
    "file": "django.core.mail.backends.filebased.EmailBackend",
    "console": "django.core.mail.backends.console.EmailBackend",
    "graph": "notifications.backends.GraphEmailBackend",
}
_email_choice = os.environ.get("EMAIL_BACKEND", "file").strip() or "file"
EMAIL_BACKEND = EMAIL_BACKENDS.get(_email_choice, _email_choice)
EMAIL_FILE_PATH = BASE_DIR / "tmp" / "emails"

# The background worker checks for emails to send this often (seconds).
WORKER_INTERVAL_SECONDS = int(os.environ.get("WORKER_INTERVAL_SECONDS", "15"))
EMAIL_MAX_ATTEMPTS = 5

# --------------------------------------------------------------------------
# Email in: turning emails to HELPDESK_MAILBOX into tickets and replies.
# --------------------------------------------------------------------------
#   off   - don't read the mailbox (default)
#   graph - the worker reads the inbox through Microsoft Graph
INBOUND_EMAIL = os.environ.get("INBOUND_EMAIL", "off").strip().lower() or "off"
# A mailbox per department (besides HELPDESK_MAILBOX, which is IT's), by the
# department's key from the admin site (Tickets > Departments):
# "mechanics=mechanics@example.com, cleaning=cs@example.com/Requests".
# Email to it becomes a ticket for that department, and that department's
# tickets are emailed from it, so replies come back to the right team. After
# a "/": read that folder instead of the Inbox (a rule files requests there,
# so the team's everyday email in the Inbox is left alone). Blank = none.
DEPARTMENT_MAILBOXES = {
    department: {
        "address": value.split("/", 1)[0].strip().lower(),
        "folder": value.split("/", 1)[1].strip() if "/" in value else "",
    }
    for department, value in env_departments("DEPARTMENT_MAILBOXES").items()
}
INBOUND_POLL_SECONDS = int(os.environ.get("INBOUND_POLL_SECONDS", "60"))
# Only accept email from these domains. Blank means the domain of
# HELPDESK_MAILBOX (blank too, as on a PC without one, means any domain).
INBOUND_ALLOWED_DOMAINS = [d.lower() for d in env_list("INBOUND_ALLOWED_DOMAINS")] or (
    [HELPDESK_MAILBOX.rsplit("@", 1)[-1].lower()] if "@" in HELPDESK_MAILBOX else []
)
# Category for tickets that arrive by email (IT can change it).
INBOUND_DEFAULT_CATEGORY = os.environ.get("INBOUND_DEFAULT_CATEGORY", "Other")
# Processed emails are moved to this folder in the mailbox.
INBOUND_PROCESSED_FOLDER = "Processed by InH-Ticketing"
INBOUND_MAX_ATTEMPTS = 3

# --------------------------------------------------------------------------
# Security. Hardened automatically whenever DEBUG is off.
# --------------------------------------------------------------------------
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # On the server, a reverse proxy (Caddy, see compose.prod.yaml) terminates
    # HTTPS and tells Django "this was HTTPS" with this header. The proxy
    # always replaces any value the browser sent, so it can't be faked.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    # Send plain-HTTP requests to HTTPS. The proxy already does this; this is a
    # second line of defence. Only an explicit False/0/no/off turns it off.
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "").strip().lower() not in {
        "0", "false", "no", "off",
    }
    # ...except the health check. Docker's HEALTHCHECK (see Dockerfile) asks
    # for http://127.0.0.1:8000/healthz inside the container, not through the
    # proxy. Redirecting it to HTTPS would mark a healthy app as unhealthy.
    SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
    # The same check sends "Host: 127.0.0.1:8000"; without this, Django would
    # answer it with 400 Bad Request. Nothing outside the container can use
    # it: in production port 8000 isn't published, and the proxy only passes on
    # requests for the real hostname.
    if "127.0.0.1" not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append("127.0.0.1")

    # HSTS: once a browser has used the site over HTTPS, for this many seconds
    # it refuses plain HTTP, and certificate warnings can't be clicked past.
    # Default: one year. The proxy sends the same value (compose.prod.yaml).
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS") or 31_536_000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # Preloading is only for public domains submitted to browser makers. This
    # hostname is internal-only, so it can't be preloaded: don't warn about it.
    SECURE_HSTS_PRELOAD = False
    SILENCED_SYSTEM_CHECKS = ["security.W021"]

# Django's test client talks plain HTTP. This runner switches the HTTPS
# redirect off for `manage.py test`; the tests of the redirect itself turn it
# back on (core/tests/test_security.py).
TEST_RUNNER = "config.runner.PlainHttpTestRunner"

# --------------------------------------------------------------------------
# Logging: everything to the console, which Docker collects.
# --------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"), "propagate": False},
    },
}
