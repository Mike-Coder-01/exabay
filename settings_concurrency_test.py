
"""
Isolated PostgreSQL concurrency-test settings.

Never use these settings for production traffic.
"""

import os

from django.core.exceptions import ImproperlyConfigured

from exabay.settings import *


TEST_DATABASE_NAME = "exxabay_concurrency_test"

if os.environ.get("EXXABAY_CONCURRENCY_TEST") != "YES":
    raise ImproperlyConfigured(
        "Concurrency test environment is not enabled."
    )

if os.environ.get("AZAMPAY_AUTOMATIC_DISBURSEMENTS_ENABLED", "").lower() in (
    "true",
    "1",
    "yes",
):
    raise ImproperlyConfigured(
        "Automatic disbursements must be disabled."
    )

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": TEST_DATABASE_NAME,
        "USER": "exxabay_concurrency",
        "PASSWORD": os.environ.get(
            "EXXABAY_CONCURRENCY_DB_PASSWORD", ""
        ),
        "HOST": "db",
        "PORT": "5432",
        "CONN_MAX_AGE": 0,
        "TEST": {
            "NAME": TEST_DATABASE_NAME,
        },
    }
}

if not DATABASES["default"]["PASSWORD"]:
    raise ImproperlyConfigured(
        "Missing concurrency database password."
    )

AZAMPAY_AUTOMATIC_DISBURSEMENTS_ENABLED = False
