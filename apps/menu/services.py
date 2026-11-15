import json

from django.core.cache import cache
from django.db import transaction
from rest_framework.renderers import JSONRenderer

from apps.core.services import notify_frontend_revalidate

from .models import Category, Dish, Option, OptionGroup, SubCategory
from .selectors import public_menu
from .serializers import CategorySerializer

MENU_CACHE_TTL = 60 * 10
MENU_VERSION_KEY = "menu:version"


def get_public_menu(request):
    """Carte publique complète, servie depuis le cache (10 min) ou reconstruite."""
    key = f"menu:public:v{_menu_version()}:{request.get_host()}"
    data = cache.get(key)
    if data is None:
        categories = CategorySerializer(public_menu(), many=True, context={"request": request}).data
        # Une catégorie sans sous-catégorie visible n'est pas affichée
        data = json.loads(JSONRenderer().render([c for c in categories if c["subcategories"]]))
        cache.set(key, data, MENU_CACHE_TTL)
    return data


def set_dish_availability(dish, is_available):
    """Rupture de stock ou retour d'un plat ; l'enregistrement vide le cache de la carte (signal post_save)."""
    if dish.is_available != is_available:
        dish.is_available = is_available
        dish.save(update_fields=["is_available", "updated_at"])
        from apps.orders import events  # import local : la carte ne dépend des commandes que pour prévenir les écrans

        transaction.on_commit(lambda: events.dish_availability(dish))
    return dish


def invalidate_menu_cache():
    """Appelé à chaque modification de la carte, après validation de la transaction."""
    transaction.on_commit(_bump_menu_version)
    notify_frontend_revalidate(["menu"])


def _menu_version():
    return cache.get_or_set(MENU_VERSION_KEY, 1, timeout=None)


def _bump_menu_version():
    try:
        cache.incr(MENU_VERSION_KEY)
    except ValueError:  # clé absente (cache vidé)
        cache.set(MENU_VERSION_KEY, 2, timeout=None)


# --- Gestion de la carte (gérant) ---

REORDERABLE = {"category": (Category, None), "subcategory": (SubCategory, "category_id"), "dish": (Dish, "subcategory_id")}


def _next_position(queryset):
    last = queryset.order_by("-position").values_list("position", flat=True).first()
    return 0 if last is None else last + 1


@transaction.atomic
def save_dish(dish, data):
    """Crée ou modifie un plat. Si option_groups est fourni, il remplace les groupes du plat :
    un groupe ou une option dont l'id est connu est mis à jour, les autres sont créés, ceux qui manquent supprimés."""
    data = dict(data)
    groups = data.pop("option_groups", None)
    was_available = dish.is_available if dish else None

    if dish is None:
        dish = Dish(**data)
        dish.position = _next_position(Dish.objects.filter(subcategory=dish.subcategory))
    else:
        for field, value in data.items():
            setattr(dish, field, value)
    dish.save()

    if groups is not None:
        _replace_option_groups(dish, groups)

    if was_available is not None and was_available != dish.is_available:
        from apps.orders import events  # import local, comme set_dish_availability

        transaction.on_commit(lambda: events.dish_availability(dish))
    if hasattr(dish, "_prefetched_objects_cache"):
        dish._prefetched_objects_cache.clear()
    return dish


def _replace_option_groups(dish, groups):
    existing = {group.id: group for group in dish.option_groups.all()}
    kept = []
    for position, group_data in enumerate(groups):
        group_data = dict(group_data)
        options = group_data.pop("options")
        group = existing.get(group_data.pop("id", None)) or OptionGroup(dish=dish)
        for field, value in group_data.items():
            setattr(group, field, value)
        group.position = position
        group.save()
        kept.append(group.id)

        known = {option.id: option for option in group.options.all()}
        kept_options = []
        for option_position, option_data in enumerate(options):
            option_data = dict(option_data)
            option = known.get(option_data.pop("id", None)) or Option(group=group)
            for field, value in option_data.items():
                setattr(option, field, value)
            option.position = option_position
            option.save()
            kept_options.append(option.id)
        group.options.exclude(id__in=kept_options).delete()
    dish.option_groups.exclude(id__in=kept).delete()


def create_in_order(serializer):
    """Nouvelle catégorie ou sous-catégorie : placée à la fin de sa liste."""
    model = serializer.Meta.model
    siblings = model.objects.all()
    if model is SubCategory:
        siblings = siblings.filter(category=serializer.validated_data["category"])
    return serializer.save(position=_next_position(siblings))


@transaction.atomic
def reorder(level, ids):
    """Range les éléments d'un même parent dans l'ordre donné. Refuse une liste incomplète ou mélangée."""
    model, parent = REORDERABLE[level]
    items = {item.id: item for item in model.objects.filter(id__in=ids)}
    if len(items) != len(ids) or len(set(ids)) != len(ids):
        raise ValueError("Un des éléments n'existe pas ou figure deux fois.")
    siblings = model.objects.all()
    if parent:
        parents = {getattr(item, parent) for item in items.values()}
        if len(parents) != 1:
            raise ValueError("Les éléments doivent appartenir au même parent.")
        siblings = siblings.filter(**{parent: parents.pop()})
    if siblings.count() != len(ids):
        raise ValueError("La liste doit contenir tous les éléments du même parent.")
    for position, item_id in enumerate(ids):
        item = items[item_id]
        if item.position != position:
            item.position = position
            item.save(update_fields=["position", "updated_at"])


def set_photo(instance, file):
    """Remplace la photo (convertie en WebP par le modèle) ; file=None la retire."""
    if file is None:
        if instance.photo:
            instance.photo.delete(save=False)
        instance.photo = ""
    else:
        instance.photo = file
    instance.save()
    return instance
