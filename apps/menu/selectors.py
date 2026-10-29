from django.db.models import Prefetch

from .models import Category, Dish, Option, OptionGroup, SubCategory


def _option_groups():
    """Groupes d'options avec seulement les options disponibles."""
    return Prefetch(
        "option_groups",
        queryset=OptionGroup.objects.prefetch_related(
            Prefetch("options", queryset=Option.objects.filter(is_available=True))
        ),
    )


def available_dishes():
    """Plats visibles par le public : disponibles, dans une sous-catégorie et une catégorie actives."""
    return Dish.objects.filter(
        is_available=True,
        subcategory__is_active=True,
        subcategory__category__is_active=True,
    )


def public_menu():
    """Catégories → sous-catégories → plats → groupes → options, en 5 requêtes."""
    dishes = available_dishes().prefetch_related(_option_groups())
    subcategories = SubCategory.objects.filter(is_active=True).prefetch_related(Prefetch("dishes", queryset=dishes))
    return Category.objects.filter(is_active=True).prefetch_related(
        Prefetch("subcategories", queryset=subcategories)
    )


def public_dish(slug):
    """Un plat disponible avec ses options, ou None."""
    return (
        available_dishes()
        .select_related("subcategory__category")
        .prefetch_related(_option_groups())
        .filter(slug=slug)
        .first()
    )


def featured_dishes():
    return (
        available_dishes()
        .filter(is_featured=True)
        .select_related("subcategory__category")
        .prefetch_related(_option_groups())
    )
