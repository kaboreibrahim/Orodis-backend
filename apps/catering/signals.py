from django.db.models.signals import post_delete, post_save

from .models import CateringFormula
from .services import invalidate_formulas_cache


def _on_formula_change(sender, **kwargs):
    invalidate_formulas_cache()


post_save.connect(_on_formula_change, sender=CateringFormula, dispatch_uid="formulas_cache_save")
post_delete.connect(_on_formula_change, sender=CateringFormula, dispatch_uid="formulas_cache_delete")
