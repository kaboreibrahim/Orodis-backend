from django.apps import AppConfig


class MenuConfig(AppConfig):
    name = "apps.menu"
    verbose_name = "Carte"

    def ready(self):
        from . import signals  # noqa: F401
