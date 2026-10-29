from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    verbose_name = "Restaurant"

    def ready(self):
        from . import signals  # noqa: F401
