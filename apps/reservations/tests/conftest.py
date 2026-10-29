import datetime as dt

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import DAYS, RestaurantSettings


@pytest.fixture
def restaurant(db):
    """Ouvert 11:00–23:00 tous les jours, créneaux de 30 min, 10 couverts par créneau, groupe max 12."""
    rs = RestaurantSettings.load()
    rs.opening_hours = {d: [["11:00", "23:00"]] for d in DAYS}
    rs.reservation_slot_minutes = 30
    rs.reservation_max_party = 12
    rs.reservation_covers_per_slot = 10
    rs.save()
    return rs


@pytest.fixture
def day():
    return timezone.localdate() + dt.timedelta(days=7)


@pytest.fixture
def make_user(django_user_model):
    return lambda role: django_user_model.objects.create_user(username=role, password="x", role=role)


@pytest.fixture
def manager(make_user):
    return make_user("manager")


@pytest.fixture
def api():
    return APIClient()
