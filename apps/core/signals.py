from django.db.models.signals import post_save

from .models import RestaurantSettings
from .services import notify_frontend_revalidate


def _on_settings_change(sender, **kwargs):
    notify_frontend_revalidate(["settings"])


post_save.connect(_on_settings_change, sender=RestaurantSettings, dispatch_uid="settings_revalidate")
