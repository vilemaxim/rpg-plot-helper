from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured


class InterviewsConfig(AppConfig):
    name = "interviews"

    def ready(self):
        """Reconcile each draft as it is submitted, where its World says to.
        Read and check the Interview config, so a bad one stops the app
        here, naming the key, and not at someone's first turn."""
        from canon import intake

        from . import config, reconciling
        intake.submitted.connect(reconciling.on_submission,
                                 dispatch_uid="reconcile-on-submission")
        try:
            config.configure()
        except config.ConfigError as error:
            raise ImproperlyConfigured(str(error)) from None
