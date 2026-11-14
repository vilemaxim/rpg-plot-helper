"""Settings for running on your own machine, and for the tests.

Postgres is the one started by `scripts/db.sh`. Emails are printed in the
terminal instead of sent.
"""

import os

import dj_database_url

from .base import *  # noqa: F401,F403

DEBUG = True
SECRET_KEY = "local-development-only-not-a-secret"
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

DATABASES = {
    "default": dj_database_url.parse(
        os.environ.get("DATABASE_URL",
                       "postgres://plothelper:plothelper@localhost:5432/plothelper")
    )
}

EMAIL_BACKEND = "accounts.email.TerminalEmailBackend"
