import datetime as dt

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.orders import selectors, services
from apps.orders.models import Receipt

from .conftest import line

pytestmark = pytest.mark.django_db


def staff_api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def journee(menu, session, staff):
    """Aujourd'hui : garba 3 500 F en espèces puis kedjenou ×2 (9 000 F) par Wave ; un kedjenou (4 500 F) non payé.
    Hier : un garba en espèces."""
    garba = services.place_order(session=session, items=[line(menu["garba"])])
    kedjenou = services.place_order(session=session, items=[line(menu["kedjenou"], menu["attieke"], quantity=2)])
    hier = services.place_order(session=session, items=[line(menu["garba"])])
    services.place_order(session=session, items=[line(menu["kedjenou"], menu["attieke"])])
    especes = services.pay(session, "cash", "", staff["cashier"], order_ids=[garba.id])
    wave = services.pay(session, "wave", "W-1", staff["cashier"], order_ids=[kedjenou.id])
    recu_hier = services.pay(session, "cash", "", staff["cashier"], order_ids=[hier.id])
    now = timezone.now()
    Receipt.objects.filter(pk=especes.pk).update(paid_at=now - dt.timedelta(minutes=5))
    Receipt.objects.filter(pk=wave.pk).update(paid_at=now)
    Receipt.objects.filter(pk=recu_hier.pk).update(paid_at=now - dt.timedelta(days=1))
    return {"especes": especes, "wave": wave, "hier": recu_hier}


def test_recus_du_jour_du_plus_recent_au_plus_ancien(journee):
    data = selectors.payments()
    assert [r.number for r in data["receipts"]] == [journee["wave"].number, journee["especes"].number]
    assert data["revenue"] == 12500 and data["receipts_count"] == 2
    assert data["receipts"][0].orders_count == 1


def test_les_quatre_moyens_sont_toujours_presents(journee):
    by_method = {m["method"]: (m["total"], m["count"]) for m in selectors.payments()["by_method"]}
    assert by_method == {"cash": (3500, 1), "wave": (9000, 1), "orange_money": (0, 0), "mtn_momo": (0, 0)}


def test_reste_a_encaisser_par_table(journee, table):
    assert selectors.payments()["to_collect"] == {
        "total": 4500, "tables": [{"table_number": table.number, "total": 4500, "orders_count": 1}]}


def test_un_autre_jour(journee):
    data = selectors.payments(timezone.localdate() - dt.timedelta(days=1))
    assert [r.number for r in data["receipts"]] == [journee["hier"].number] and data["revenue"] == 3500


def test_route_caisse_et_gerant(journee, staff):
    assert APIClient().get("/api/v1/manage/payments/").status_code == 401
    assert staff_api(staff["kitchen"]).get("/api/v1/manage/payments/").status_code == 403
    response = staff_api(staff["cashier"]).get("/api/v1/manage/payments/")
    assert response.status_code == 200
    row = response.data["receipts"][0]
    assert row["method_display"] == "Wave" and row["transaction_ref"] == "W-1" and row["table_number"] is not None
    hier = (timezone.localdate() - dt.timedelta(days=1)).isoformat()
    assert staff_api(staff["manager"]).get(f"/api/v1/manage/payments/?date={hier}").data["receipts_count"] == 1
    assert staff_api(staff["manager"]).get("/api/v1/manage/payments/?date=hier").status_code == 400
