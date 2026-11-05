"""
Django settings for InH-Ticketing.

Everything that differs between your PC and the server (secrets, database,
hostnames, Entra IDs) comes from environment variables. For local development
those live in a `.env` file next to manage.py; see `.env.example`.
"""

import os
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
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
SESSION_COOKIE_AGE = 60 * 60 * 12  # 12 hours
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
# Security. Hardened automatically whenever DEBUG is off.
# --------------------------------------------------------------------------
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # The server will sit behind a reverse proxy that terminates HTTPS
    # (milestone 6). This tells Django to trust its "this was HTTPS" header.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

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
