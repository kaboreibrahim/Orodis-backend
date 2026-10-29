import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _cache_en_memoire(settings):
    """Les tests n'utilisent jamais le Redis de dev (cache de la carte, compteurs de throttling)."""
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    cache.clear()
