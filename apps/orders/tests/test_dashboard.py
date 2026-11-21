import datetime as dt

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.orders import selectors, services
from apps.orders.models import Order, Receipt

from .conftest import line

pytestmark = pytest.mark.django_db


def staff_api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def service_du_jour(menu, session, staff):
    """Aujourd'hui : garba 3 500 F payé en espèces, kedjenou ×2 (9 000 F) payé par Wave, un garba annulé,
    un kedjenou (4 500 F) pas encore payé. Hier : un garba payé en espèces."""
    garba = services.place_order(session=session, items=[line(menu["garba"])])
    kedjenou = services.place_order(session=session, items=[line(menu["kedjenou"], menu["attieke"], quantity=2)])
    annulee = services.place_order(session=session, items=[line(menu["garba"])])
    hier = services.place_order(session=session, items=[line(menu["garba"])])
    services.place_order(session=session, items=[line(menu["kedjenou"], menu["attieke"])])  # reste à encaisser
    services.cancel(annulee, staff["manager"], "Erreur de saisie")
    services.pay(session, "cash", "", staff["cashier"], order_ids=[garba.id])
    services.pay(session, "wave", "W-1", staff["cashier"], order_ids=[kedjenou.id])
    recu_hier = services.pay(session, "cash", "", staff["cashier"], order_ids=[hier.id])
    yesterday = timezone.now() - dt.timedelta(days=1)
    Order.objects.filter(pk=hier.pk).update(created_at=yesterday)
    Receipt.objects.filter(pk=recu_hier.pk).update(paid_at=yesterday)


def test_chiffres_du_jour_et_comparaison_avec_la_veille(service_du_jour):
    data = selectors.dashboard("today")
    assert data["current"] == {"revenue": 12500, "receipts_count": 2, "orders_count": 3, "cancelled_count": 1, "average_ticket": 6250}
    assert data["previous"]["revenue"] == 3500 and data["previous"]["orders_count"] == 1
    assert [(m["method"], m["label"], m["total"], m["count"]) for m in data["by_method"]] == [
        ("wave", "Wave", 9000, 1), ("cash", "Espèces", 3500, 1)]


def test_sept_derniers_jours_dans_l_ordre(service_du_jour):
    trend = selectors.dashboard("today")["trend"]
    today = timezone.localdate()
    assert [d["date"] for d in trend] == [today - dt.timedelta(days=n) for n in range(6, -1, -1)]
    assert [d["revenue"] for d in trend] == [0, 0, 0, 0, 0, 3500, 12500]
    assert [d["orders_count"] for d in trend] == [0, 0, 0, 0, 0, 1, 3]


def test_plats_les_plus_vendus_hors_annulations(service_du_jour):
    top = selectors.dashboard("today")["top_dishes"]
    assert [(d["dish_name"], d["quantity"], d["revenue"]) for d in top] == [
        ("Kedjenou de poulet", 3, 13500), ("Garba spécial", 1, 3500)]


def test_semaine_inclut_la_veille(service_du_jour):
    data = selectors.dashboard("week")
    assert data["current"]["revenue"] == 16000 and data["current"]["orders_count"] == 4
    assert data["start"] == timezone.localdate() - dt.timedelta(days=6)


def test_etat_de_la_salle(service_du_jour, menu, other_table):
    menu["garba"].is_available = False
    menu["garba"].save()
    live = selectors.dashboard("today")["live"]
    assert live == {"tables_total": 2, "tables_open": 1, "active_orders": 4, "open_requests": 0,
                    "to_collect": 4500, "unavailable_dishes": ["Garba spécial"]}


def test_route_reservee_au_gerant(service_du_jour, staff):
    assert staff_api(staff["cashier"]).get("/api/v1/manage/dashboard/").status_code == 403
    assert APIClient().get("/api/v1/manage/dashboard/").status_code == 401
    response = staff_api(staff["manager"]).get("/api/v1/manage/dashboard/?period=month")
    assert response.status_code == 200 and response.data["current"]["revenue"] == 16000
    assert staff_api(staff["manager"]).get("/api/v1/manage/dashboard/?period=annee").status_code == 400


# --- Dates libres, affluence, catégories ---------------------------------------------------------

def test_dates_libres(service_du_jour):
    today = timezone.localdate()
    data = selectors.dashboard(start=today - dt.timedelta(days=1), end=today - dt.timedelta(days=1))
    assert data["period"] == "custom" and data["days"] == 1
    assert data["current"]["revenue"] == 3500 and data["current"]["orders_count"] == 1
    # la courbe montre quand même 7 jours, jusqu'au dernier jour demandé
    assert data["trend"][-1]["date"] == today - dt.timedelta(days=1) and len(data["trend"]) == 7


def test_longue_periode_par_semaine(service_du_jour):
    today = timezone.localdate()
    data = selectors.dashboard(start=today - dt.timedelta(days=99), end=today)
    assert data["trend_unit"] == "week" and all(t["date"].weekday() == 0 for t in data["trend"])
    assert sum(t["revenue"] for t in data["trend"]) == 16000


@pytest.mark.parametrize("start, end, message", [
    (1, None, "début et la date de fin"),
    (0, 2, "précéder"),
    (0, -1, "futur"),
    (400, 0, "un an"),
])
def test_dates_libres_refusees(start, end, message):
    today = timezone.localdate()
    first = today - dt.timedelta(days=start) if start is not None else None
    last = (today - dt.timedelta(days=end)) if end is not None else None
    with pytest.raises(selectors.PeriodError, match=message):
        selectors.period_bounds(start=first, end=last)


def test_affluence_par_heure(service_du_jour):
    hours = selectors.dashboard("today")["by_hour"]
    assert [h["hour"] for h in hours] == list(range(24))
    assert sum(h["orders_count"] for h in hours) == 3 and sum(h["amount"] for h in hours) == 17000


def test_ventes_par_categorie(service_du_jour, menu):
    data = selectors.dashboard("today")["by_category"]
    assert sum(c["revenue"] for c in data) == 17000
    assert round(sum(c["share"] for c in data)) == 100
    assert data == sorted(data, key=lambda c: -c["revenue"])


def test_route_avec_dates_libres(service_du_jour, staff):
    today = timezone.localdate().isoformat()
    api = staff_api(staff["manager"])
    r = api.get(f"/api/v1/manage/dashboard/?start={today}&end={today}")
    assert r.status_code == 200 and r.data["period"] == "custom" and len(r.data["by_hour"]) == 24
    assert api.get("/api/v1/manage/dashboard/?start=2026-13-01&end=2026-12-01").status_code == 400


# --- Rapports PDF ----------------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "/api/v1/manage/reports/activity.pdf?period=week",
    "/api/v1/manage/reports/sales.pdf?period=month",
    "/api/v1/manage/reports/closing.pdf",
])
def test_rapports_pdf(service_du_jour, staff, url):
    r = staff_api(staff["manager"]).get(url)
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and "attachment" in r["Content-Disposition"]


def test_rapports_vides(staff, db):
    api = staff_api(staff["manager"])
    for url in ("activity.pdf?period=today", "sales.pdf?period=today", "closing.pdf"):
        assert api.get(f"/api/v1/manage/reports/{url}").content.startswith(b"%PDF")


def test_droits_des_rapports(service_du_jour, staff):
    caisse = staff_api(staff["cashier"])
    assert caisse.get("/api/v1/manage/reports/closing.pdf").status_code == 200
    assert caisse.get("/api/v1/manage/reports/activity.pdf").status_code == 403
    assert caisse.get("/api/v1/manage/reports/sales.pdf").status_code == 403
    assert staff_api(staff["kitchen"]).get("/api/v1/manage/reports/closing.pdf").status_code == 403
    demain = (timezone.localdate() + dt.timedelta(days=1)).isoformat()
    assert caisse.get(f"/api/v1/manage/reports/closing.pdf?date={demain}").status_code == 400


def test_nom_du_fichier(service_du_jour, staff):
    today = timezone.localdate()
    r = staff_api(staff["manager"]).get(f"/api/v1/manage/reports/sales.pdf?start={today}&end={today}")
    assert f'orodis-ventes-{today:%Y-%m-%d}.pdf' in r["Content-Disposition"]
