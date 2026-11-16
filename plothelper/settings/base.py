"""Settings shared by every environment. `local` builds on this; settings for a
deployed copy will too, when deployment is built."""

import os
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
    "canon",
    "interviews",
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
                "organizations.context.organization",
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

# ── Interviews ──────────────────────────────────────────────────────────────
# Which LLM each kind of Interview uses, and whether it is on at all
# (ADR-0008, interviews/config.py). The file at the repo root is committed with
# defaults; INTERVIEWS_CONFIG names another.
INTERVIEWS_CONFIG = os.environ.get("INTERVIEWS_CONFIG") or BASE_DIR / "interviews.toml"

# ── Everything else ─────────────────────────────────────────────────────────

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

# ── Uploads ─────────────────────────────────────────────────────────────────
# Nothing is written to the app's own disk (ADR-0003), so an upload is held in
# memory and never spooled to a temporary file. That makes the size limit a
# hard one: a larger upload is refused.
FILE_UPLOAD_HANDLERS = ["django.core.files.uploadhandler.MemoryFileUploadHandler"]
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

# A zip is not trusted. These bound what an imported World may unpack to.
IMPORT_MAX_FILES = 5000
IMPORT_MAX_FILE_BYTES = 1024 * 1024
IMPORT_MAX_UNPACKED_BYTES = 50 * 1024 * 1024

# A Twine file submitted as a Mod. A published Twine story carries its story
# format's code, several hundred KB of it, so it is allowed more than a Mod
# file. This is plotcanon's own limit: it refuses, unread, anything over
# 5,000,000 bytes, and does not export the number, so it is written here and
# canon/test_twine.py checks the two agree. The Mod a Twine file converts to
# is still held to IMPORT_MAX_FILE_BYTES.
TWINE_MAX_FILE_BYTES = 5_000_000

# Private links to a Mod for Mod Runners (canon/links.py): how many links
# that open nothing one address may present, and for how many seconds those
# failures count, before it is refused.
MOD_LINK_FAILURES_ALLOWED = 20
MOD_LINK_FAILURE_WINDOW = 15 * 60

# Sign-in links (accounts/views.py): how many one address may be sent, and
# one requester may ask for, in how many seconds. A person who is over a limit
# sees the same page as anyone, and no email is sent. An account that asked
# for a link and never used one is removed after SIGN_IN_UNUSED_ACCOUNT_AGE.
SIGN_IN_LINKS_PER_ADDRESS = 1
SIGN_IN_ADDRESS_WINDOW = 5 * 60
SIGN_IN_LINKS_PER_REQUESTER = 10
SIGN_IN_REQUESTER_WINDOW = 60 * 60
SIGN_IN_UNUSED_ACCOUNT_AGE = timedelta(days=1)

# How many proxies of our own stand in front of the app, such as a load
# balancer. With none, a request's address is the one it came from; with
# some, it is read from X-Forwarded-For. Used by every limit.
TRUSTED_PROXIES = 0
