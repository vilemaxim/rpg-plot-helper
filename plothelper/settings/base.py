"""Settings shared by every environment. `local` builds on this; settings for a
deployed copy will too, when deployment is built."""

from datetime import timedelta
from pathlib import Path

from . import env

BASE_DIR = Path(__file__).resolve().parent.parent.parent

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "organizations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.SignInRequiredMiddleware",
    "organizations.tenancy.OrganizationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "plothelper.urls"

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
            ],
        },
    },
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Accounts ────────────────────────────────────────────────────────────────
# People sign in with a link sent to their email. There are no passwords.

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["sesame.backends.ModelBackend"]
LOGIN_URL = "sign-in"
LOGIN_REDIRECT_URL = "home"

# A sign-in link works once, and only for a short while.
SESAME_ONE_TIME = True
SESAME_MAX_AGE = timedelta(minutes=15)

DEFAULT_FROM_EMAIL = "RPG Plot Helper <no-reply@localhost>"

# ── Organizations ───────────────────────────────────────────────────────────
# Who may create an Organization (ADR-0005). Off: the first person to sign in
# creates the one Organization, and everyone after joins only by invitation.
# On: everyone who signs up gets an Organization of their own.
OPEN_SIGN_UP = env.flag("OPEN_SIGN_UP", default=False)

# ── Everything else ─────────────────────────────────────────────────────────

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
