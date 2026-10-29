import datetime as dt

import pytest
from django.utils import timezone

from apps.catering.models import CateringFormula
from apps.core.models import RestaurantSettings


@pytest.fixture
def restaurant(db):
    rs = RestaurantSettings.load()
    rs.whatsapp = "07 00 00 00 00"
    rs.catering_min_guests = 20
    rs.save()
    return rs


@pytest.fixture
def buffet(db):
    return CateringFormula.objects.create(name="Buffet", items=["Entrées"], is_highlighted=True)


@pytest.fixture
def quote_data(buffet):
    return {
        "event_type": "mariage", "event_date": timezone.localdate() + dt.timedelta(days=30),
        "guests": 150, "place_type": "domicile", "place_detail": "Cocody", "formula": buffet,
        "name": "Awa Koné", "whatsapp": "07 07 07 07 07", "email": "awa@example.com", "message": "Budget 2 M",
    }
