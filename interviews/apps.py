from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured


class InterviewsConfig(AppConfig):
    name = "interviews"

    def ready(self):
        """Read and check the Interview config, so a bad one stops the app
        here, naming the key, and not at someone's first turn."""
        from . import config
        try:
            config.configure()
        except config.ConfigError as error:
            raise ImproperlyConfigured(str(error)) from None
