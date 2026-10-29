from django.apps import AppConfig


class CateringConfig(AppConfig):
    name = "apps.catering"
    verbose_name = "Traiteur"

    def ready(self):
        from . import signals  # noqa: F401
