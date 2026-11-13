import datetime as dt

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.menu import services as menu_services
from apps.orders import selectors, services
from apps.orders.models import Event

from .conftest import line

pytestmark = pytest.mark.django_db
TABLE, STAFF = "/api/v1/table/events/", "/api/v1/manage/events/"


def table_client(session):
    client = APIClient()
    client.credentials(HTTP_X_SESSION_TOKEN=session.token)
    return client


def staff_client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def read(client, path, after=0):
    return [(e["type"], e["data"]) for e in client.get(path, {"after": after}).json()["events"]]


# --- Routes ----------------------------------------------------------------------------------

def test_routes_refusees_sans_session_ni_jwt(api):
    assert api.get(TABLE).status_code == 401
    assert api.get(STAFF).status_code == 401


def test_ouverture_de_l_ecran_sans_curseur(menu, session, staff, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        services.place_order(session=session, items=[line(menu["garba"])])
    caisse = staff_client(staff["cashier"])
    data = caisse.get(STAFF).json()
    assert data == {"cursor": Event.objects.latest("id").id, "events": []}
    assert caisse.get(STAFF, {"after": data["cursor"]}).json() == {"cursor": data["cursor"], "events": []}


# --- Événements : chacun aux bons destinataires uniquement ----------------------------------

def test_commande_creee_et_suivie(menu, session, other_table, staff, django_capture_on_commit_callbacks):
    other = services.open_session(str(other_table.qr_token))
    caisse, cuisine = staff_client(staff["cashier"]), staff_client(staff["kitchen"])
    phone, other_phone = table_client(session), table_client(other)

    with django_capture_on_commit_callbacks(execute=True):
        order = services.place_order(session=session, items=[line(menu["garba"])])
    for client in (caisse, cuisine):
        [(kind, data)] = read(client, STAFF)  # une seule fois, même pour la cuisine
        assert kind == "order.created" and data["number"] == order.number
    assert read(phone, TABLE) == [] and read(other_phone, TABLE) == []

    cursor = selectors.latest_event_id()
    with django_capture_on_commit_callbacks(execute=True):
        services.advance(order, staff["kitchen"])
    for client, path in ((caisse, STAFF), (cuisine, STAFF), (phone, TABLE)):
        [(kind, data)] = read(client, path, cursor)
        assert kind == "order.status" and data["status"] == "preparing"
    assert read(other_phone, TABLE, cursor) == []  # l'autre table ne sait rien

    cursor = selectors.latest_event_id()
    with django_capture_on_commit_callbacks(execute=True):
        services.cancel(order, staff["cashier"], "Client parti")
    assert read(phone, TABLE, cursor) == [
        ("order.cancelled", {"id": order.id, "number": order.number, "reason": "Client parti"})]


def test_demandes_de_la_table(session, staff, django_capture_on_commit_callbacks):
    serveur, cuisine, phone = staff_client(staff["waiter"]), staff_client(staff["kitchen"]), table_client(session)

    with django_capture_on_commit_callbacks(execute=True):
        request, _ = services.request_service(session, "waiter")
    assert read(serveur, STAFF) == [("request.created", {"id": request.id, "table_number": 5, "kind": "waiter"})]
    assert read(cuisine, STAFF) == [] and read(phone, TABLE) == []

    cursor = selectors.latest_event_id()
    with django_capture_on_commit_callbacks(execute=True):
        services.request_service(session, "waiter")  # doublon : aucun nouvel événement
    assert read(serveur, STAFF, cursor) == []

    with django_capture_on_commit_callbacks(execute=True):
        services.complete_request(request, staff["waiter"])
    for client, path in ((serveur, STAFF), (phone, TABLE)):
        assert read(client, path, cursor) == [("request.done", {"id": request.id, "kind": "waiter"})]


def test_rupture_de_stock_pour_tous(menu, session, staff, django_capture_on_commit_callbacks):
    readers = [(staff_client(staff["manager"]), STAFF), (staff_client(staff["kitchen"]), STAFF), (table_client(session), TABLE)]
    with django_capture_on_commit_callbacks(execute=True):
        menu_services.set_dish_availability(menu["garba"], False)
    for client, path in readers:
        assert read(client, path) == [("dish.availability", {"dish_id": menu["garba"].id, "is_available": False})]

    cursor = selectors.latest_event_id()
    with django_capture_on_commit_callbacks(execute=True):
        menu_services.set_dish_availability(menu["garba"], False)  # inchangé : rien
    assert read(*readers[0], cursor) == []


def test_erreur_d_ecriture_n_empeche_pas_la_commande(menu, session, monkeypatch, django_capture_on_commit_callbacks):
    def broken(*args, **kwargs):
        raise RuntimeError("Base injoignable")

    monkeypatch.setattr(Event.objects, "bulk_create", broken)
    with django_capture_on_commit_callbacks(execute=True):
        order = services.place_order(session=session, items=[line(menu["garba"])])
    assert order.pk and order.number


# --- Purge ------------------------------------------------------------------------------------

def test_purge_events(session):
    old, recent = (Event.objects.create(audience=Event.Audience.STAFF, kind="order.status") for _ in range(2))
    Event.objects.filter(pk=old.pk).update(created_at=timezone.now() - dt.timedelta(hours=25))
    assert services.purge_events() == 1
    assert list(Event.objects.values_list("pk", flat=True)) == [recent.pk]
