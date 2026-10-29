from django.db.models.signals import post_delete, post_save

from .models import Category, Dish, Option, OptionGroup, SubCategory
from .services import invalidate_menu_cache


def _on_menu_change(sender, **kwargs):
    invalidate_menu_cache()


for model in (Category, SubCategory, Dish, OptionGroup, Option):
    post_save.connect(_on_menu_change, sender=model, dispatch_uid=f"menu_cache_save_{model.__name__}")
    post_delete.connect(_on_menu_change, sender=model, dispatch_uid=f"menu_cache_delete_{model.__name__}")
