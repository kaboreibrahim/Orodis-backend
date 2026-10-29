import json

from django.core.cache import cache
from django.db import transaction
from rest_framework.renderers import JSONRenderer

from apps.core.services import notify_frontend_revalidate

from .selectors import public_menu
from .serializers import CategorySerializer

MENU_CACHE_TTL = 60 * 10
MENU_VERSION_KEY = "menu:version"


def get_public_menu(request):
    """Carte publique complète, servie depuis Redis (10 min) ou reconstruite."""
    key = f"menu:public:v{_menu_version()}:{request.get_host()}"
    data = cache.get(key)
    if data is None:
        categories = CategorySerializer(public_menu(), many=True, context={"request": request}).data
        # Une catégorie sans sous-catégorie visible n'est pas affichée
        data = json.loads(JSONRenderer().render([c for c in categories if c["subcategories"]]))
        cache.set(key, data, MENU_CACHE_TTL)
    return data


def invalidate_menu_cache():
    """Appelé à chaque modification de la carte, après validation de la transaction."""
    transaction.on_commit(_bump_menu_version)
    notify_frontend_revalidate(["menu"])


def _menu_version():
    return cache.get_or_set(MENU_VERSION_KEY, 1, timeout=None)


def _bump_menu_version():
    try:
        cache.incr(MENU_VERSION_KEY)
    except ValueError:  # clé absente (Redis vidé)
        cache.set(MENU_VERSION_KEY, 2, timeout=None)
