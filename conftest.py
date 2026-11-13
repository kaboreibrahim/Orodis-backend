import pytest
from django.core.cache import cache
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _cache_en_memoire(settings):
    """Cache en mémoire pour les tests : pas de table orodis_cache à créer (carte, compteurs de throttling)."""
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    cache.clear()


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def make_user(django_user_model):
    """make_user("cashier") : un membre du personnel avec ce rôle (mot de passe « x »)."""
    return lambda role, **extra: django_user_model.objects.create_user(username=role, password="x", role=role, **extra)


@pytest.fixture
def as_role(api, make_user):
    """as_role("manager") : le client API connecté avec ce rôle ; as_role(None) : visiteur anonyme."""

    def login(role):
        if role:
            api.force_authenticate(make_user(role))
        return api

    return login
