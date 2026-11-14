from django.db import connection
from django.test import TestCase


class TheDatabase(TestCase):
    def test_the_tests_run_against_postgres(self):
        """Row-level security is part of the design, so the tests must never
        run against anything else (ADR-0003)."""
        self.assertEqual(connection.vendor, "postgresql")
