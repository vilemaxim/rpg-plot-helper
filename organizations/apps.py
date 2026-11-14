from django.apps import AppConfig


class OrganizationsConfig(AppConfig):
    name = "organizations"

    def ready(self):
        from . import checks, signup  # noqa: F401  (register the check and the signal)
