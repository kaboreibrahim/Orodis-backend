import pytest
from rest_framework.test import APIClient

from apps.orders import services
from apps.orders.authentication import TableSessionThrottle
from apps.orders.models import Order

from .conftest import line

pytestmark = pytest.mark.django_db
ORDERS, MANAGE = "/api/v1/table/orders/", "/api/v1/manage/"


# --- Téléphone de la table -----------------------------------------------------------------

def test_ouvrir_session(api, table, session):
    r = api.post("/api/v1/table/sessions/", {"qr_token": str(table.qr_token)}, format="json")
    assert r.status_code == 200
    assert r.json() == {"session_token": session.token, "table": {"number": 5, "zone": "Salle"}, "status": "open"}


def test_ouvrir_session_qr_invalide(api, db):
    r = api.post("/api/v1/table/sessions/", {"qr_token": "pas-un-qr"}, format="json")
    assert r.status_code == 404 and "plus valable" in r.json()["detail"]


@pytest.mark.parametrize("headers", [{}, {"HTTP_X_SESSION_TOKEN": "inconnu"}])
def test_sans_session_valide(api, db, headers):
    assert api.get("/api/v1/table/session/", **headers).status_code == 401


def test_commande_contrat_et_prix_falsifie_ignore(phone, menu):
    body = {"items": [{**line(menu["kedjenou"], menu["attieke"], quantity=2), "price": 1, "unit_price": 1}],
            "payment_timing": "now", "payment_method": "orange_money", "note": "Vite", "total": 1}
    r = phone.post(ORDERS, body, format="json")
    data = r.json()
    assert r.status_code == 201
    assert (data["status"], data["total"], data["payment_timing"], data["eta_minutes"]) == ("received", 9000, "now", 20)
    assert data["items"] == [{"dish_name": "Kedjenou de poulet", "quantity": 2, "unit_price": 4500, "options_label": "Attiéké",
                              "options_price": 0, "note": "", "line_total": 9000}]
    assert "created_by" not in data and "status_changed_by" not in data


def test_erreur_par_ligne(phone, menu):
    menu["garba"].is_available = False
    menu["garba"].save()
    r = phone.post(ORDERS, {"items": [line(menu["kedjenou"], menu["attieke"]), line(menu["garba"])]}, format="json")
    assert r.status_code == 400
    assert r.json()["items"][0] == {} and r.json()["items"][1]["dish_id"]


def test_une_table_ne_voit_pas_les_commandes_d_une_autre(phone, menu, other_table):
    other = services.open_session(str(other_table.qr_token))
    order = services.place_order(session=other, items=[line(menu["garba"])])
    assert phone.get(f"{ORDERS}{order.number}/").status_code == 404
    assert phone.get("/api/v1/table/session/").json()["orders"] == []


def test_etat_de_la_session(phone, menu, session, staff):
    kept = services.place_order(session=session, items=[line(menu["garba"])])
    cancelled = services.place_order(session=session, items=[line(menu["garba"])])
    services.cancel(cancelled, staff["cashier"], "Doublon")
    services.request_service(session, "waiter")
    data = phone.get("/api/v1/table/session/").json()
    assert data["total"] == 3500 and len(data["orders"]) == 2
    assert [r["kind"] for r in data["open_requests"]] == ["waiter"]
    assert phone.get(f"{ORDERS}{kept.number}/").json()["status"] == "received"


def test_demandes_201_puis_200(phone, session):
    assert phone.post("/api/v1/table/requests/", {"kind": "bill"}, format="json").status_code == 201
    assert phone.post("/api/v1/table/requests/", {"kind": "bill"}, format="json").status_code == 200


def test_limite_des_lectures(phone, session, monkeypatch):
    monkeypatch.setattr(TableSessionThrottle, "THROTTLE_RATES", {**TableSessionThrottle.THROTTLE_RATES, "table_read": "3/min"})
    codes = [phone.get("/api/v1/table/session/").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_limite_des_ecritures(phone, session, monkeypatch):
    monkeypatch.setattr(TableSessionThrottle, "THROTTLE_RATES", {**TableSessionThrottle.THROTTLE_RATES, "table": "2/min"})
    codes = [phone.post("/api/v1/table/requests/", {"kind": "waiter"}, format="json").status_code for _ in range(3)]
    assert codes == [201, 200, 429]


def test_lectures_et_ecritures_comptees_a_part(phone, session, monkeypatch):
    """Recharger le suivi tant qu'on veut n'empêche pas d'appeler un serveur (et inversement)."""
    rates = {**TableSessionThrottle.THROTTLE_RATES, "table": "1/min", "table_read": "2/min"}
    monkeypatch.setattr(TableSessionThrottle, "THROTTLE_RATES", rates)
    assert [phone.get("/api/v1/table/session/").status_code for _ in range(3)] == [200, 200, 429]
    assert phone.post("/api/v1/table/requests/", {"kind": "waiter"}, format="json").status_code == 201
    assert phone.post("/api/v1/table/requests/", {"kind": "bill"}, format="json").status_code == 429


# --- Personnel -------------------------------------------------------------------------------

@pytest.fixture
def orders(menu, session):
    """Une commande reçue (table 5) et une servie."""
    received = services.place_order(session=session, items=[line(menu["garba"])])
    served = services.place_order(session=session, items=[line(menu["garba"])])
    Order.objects.filter(pk=served.pk).update(status=Order.Status.SERVED)
    return received, served


def staff_api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.parametrize("role, count", [("manager", 2), ("cashier", 2), ("waiter", 2), ("kitchen", 1)])
def test_liste_par_role(staff, orders, role, count):
    r = staff_api(staff[role]).get(f"{MANAGE}orders/")
    assert r.status_code == 200 and r.json()["count"] == count


def test_liste_anonyme(api, orders):
    assert api.get(f"{MANAGE}orders/").status_code == 401


def test_filtres(staff, orders):
    api = staff_api(staff["manager"])
    assert api.get(f"{MANAGE}orders/", {"status": "received,preparing"}).json()["count"] == 1
    assert api.get(f"{MANAGE}orders/", {"table": 5}).json()["count"] == 2
    assert api.get(f"{MANAGE}orders/", {"table": 9}).json()["count"] == 0
    assert api.get(f"{MANAGE}orders/", {"date": "2020-01-01"}).json()["count"] == 0
    assert api.get(f"{MANAGE}orders/", {"date": "pas-une-date"}).status_code == 400


def test_avancer_par_l_api(staff, orders):
    received, _ = orders
    url = f"{MANAGE}orders/{received.id}/advance/"
    assert staff_api(staff["waiter"]).post(url).status_code == 403
    r = staff_api(staff["kitchen"]).post(url)
    assert r.status_code == 200 and r.json()["status"] == "preparing" and r.json()["status_changed_by"] == "kitchen"


def test_annuler_par_l_api(staff, orders):
    received, _ = orders
    url = f"{MANAGE}orders/{received.id}/cancel/"
    assert staff_api(staff["kitchen"]).post(url, {"reason": "x"}, format="json").status_code == 403
    assert staff_api(staff["cashier"]).post(url, {}, format="json").status_code == 400
    assert staff_api(staff["cashier"]).post(url, {"reason": "Client parti"}, format="json").json()["status"] == "cancelled"


@pytest.mark.parametrize("role, expected", [("cashier", 201), ("manager", 201), ("waiter", 403), ("kitchen", 403)])
def test_saisie_caisse_par_role(staff, menu, role, expected):
    r = staff_api(staff[role]).post(f"{MANAGE}orders/", {"items": [line(menu["garba"])]}, format="json")
    assert r.status_code == expected


def test_saisie_pour_une_table_rejoint_sa_session(staff, menu, session):
    r = staff_api(staff["cashier"]).post(f"{MANAGE}orders/", {"items": [line(menu["garba"])], "table_number": 5}, format="json")
    assert r.status_code == 201 and r.json()["table_number"] == 5 and r.json()["created_by"] == "cashier"
    assert session.orders.count() == 1
    bad = staff_api(staff["cashier"]).post(f"{MANAGE}orders/", {"items": [line(menu["garba"])], "table_number": 99}, format="json")
    assert bad.status_code == 400 and bad.json()["table_number"]


def test_demandes_du_personnel(staff, session):
    req, _ = services.request_service(session, "bill")
    api = staff_api(staff["waiter"])
    assert [(r["table_number"], r["kind"]) for r in api.get(f"{MANAGE}requests/").json()] == [(5, "bill")]
    assert api.post(f"{MANAGE}requests/{req.id}/done/").json()["status"] == "done"
    assert api.get(f"{MANAGE}requests/").json() == []
    assert len(api.get(f"{MANAGE}requests/", {"status": "all"}).json()) == 1
    assert staff_api(staff["kitchen"]).get(f"{MANAGE}requests/").status_code == 403


def test_tables_occupees(staff, orders, session):
    services.request_service(session, "waiter")
    data = staff_api(staff["cashier"]).get(f"{MANAGE}sessions/").json()
    assert len(data) == 1
    assert (data[0]["table"]["number"], data[0]["orders_count"], data[0]["total"], data[0]["open_requests"]) == (5, 2, 7000, ["waiter"])
