import datetime as dt

import pytest
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.orders import services
from apps.orders.models import Order, ServiceRequest, TableSession
from apps.tables.services import regenerate_qr

from .conftest import line

pytestmark = pytest.mark.django_db
S = Order.Status


# --- open_session / close_idle_sessions ------------------------------------------------------

def test_open_session_reprend_la_session_ouverte(table, session):
    assert services.open_session(str(table.qr_token)) == session


@pytest.mark.parametrize("token", ["pas-un-uuid", "3c1dffe1-ff8c-484b-8f04-d7b4ad8c4195"])
def test_open_session_qr_inconnu(token, db):
    with pytest.raises(NotFound):
        services.open_session(token)


def test_open_session_qr_regenere_ou_table_inactive(table):
    old = str(table.qr_token)
    regenerate_qr(table)
    with pytest.raises(NotFound):
        services.open_session(old)
    table.refresh_from_db()
    table.is_active = False
    table.save()
    with pytest.raises(NotFound):
        services.open_session(str(table.qr_token))


def test_nouvelle_session_apres_fermeture(table, session):
    services.close_session(session)
    assert services.open_session(str(table.qr_token)) != session


def test_close_idle_sessions(session, other_table):
    recent = services.session_for_table(other_table)
    TableSession.objects.filter(pk=session.pk).update(last_activity_at=timezone.now() - dt.timedelta(hours=7))
    assert services.close_idle_sessions() == 1
    session.refresh_from_db()
    recent.refresh_from_db()
    assert session.is_closed and not recent.is_closed


# --- place_order -------------------------------------------------------------------------------

def test_prix_recalcules_et_figes(menu, session):
    order = services.place_order(session=session, items=[
        line(menu["kedjenou"], menu["foutou"], menu["doux"], quantity=2), line(menu["garba"]),
    ], payment_method="wave")
    first, second = order.items.all()
    assert (first.unit_price, first.options_price, first.line_total) == (4500, 500, 10000)
    assert first.options_label == "Foutou · Piment doux"
    assert order.total == 13500 and order.payment_method == "wave"
    # Le plat change ensuite : la commande garde son nom et son prix
    menu["kedjenou"].price, menu["kedjenou"].name = 9999, "Autre"
    menu["kedjenou"].save()
    first.refresh_from_db()
    assert (first.dish_name, first.unit_price) == ("Kedjenou de poulet", 4500)


def test_numeros_qui_se_suivent(menu, session):
    a = services.place_order(session=session, items=[line(menu["garba"])])
    b = services.place_order(session=session, items=[line(menu["garba"])])
    assert b.number == a.number + 1


def test_temps_estime(menu, session):
    preparing = services.place_order(session=session, items=[line(menu["garba"])])
    Order.objects.filter(pk=preparing.pk).update(status=S.PREPARING)
    order = services.place_order(session=session, items=[line(menu["kedjenou"], menu["attieke"]), line(menu["garba"])])
    assert order.eta_minutes == 20 + 2  # plat le plus long + 2 min par commande en préparation


def errors_of(exc):
    return exc.value.detail["items"]


def test_option_d_un_autre_plat_refusee(menu, session):
    with pytest.raises(ValidationError) as exc:
        services.place_order(session=session, items=[line(menu["garba"]), line(menu["kedjenou"], menu["garba_option"])])
    assert errors_of(exc)[0] == {} and "invalide" in str(errors_of(exc)[1]["option_ids"][0])


@pytest.mark.parametrize("change", ["dish", "subcategory", "category"])
def test_plat_indisponible(menu, session, change):
    dish = menu["garba"]
    target = {"dish": dish, "subcategory": dish.subcategory, "category": dish.subcategory.category}[change]
    setattr(target, "is_available" if change == "dish" else "is_active", False)
    target.save()
    with pytest.raises(ValidationError) as exc:
        services.place_order(session=session, items=[line(dish)])
    assert "disponible" in str(errors_of(exc)[0]["dish_id"][0])


@pytest.mark.parametrize("options, message", [
    ((), "au moins 1"),                       # accompagnement obligatoire
    (("attieke", "foutou"), "au maximum"),    # un seul accompagnement
])
def test_choix_min_et_max(menu, session, options, message):
    with pytest.raises(ValidationError) as exc:
        services.place_order(session=session, items=[line(menu["kedjenou"], *(menu[o] for o in options))])
    assert message in str(errors_of(exc)[0]["option_ids"][0])


def test_option_indisponible(menu, session):
    menu["foutou"].is_available = False
    menu["foutou"].save()
    with pytest.raises(ValidationError) as exc:
        services.place_order(session=session, items=[line(menu["kedjenou"], menu["foutou"])])
    assert "Foutou" in str(errors_of(exc)[0]["option_ids"][0])


def test_limites_lignes_et_quantite(menu, session):
    with pytest.raises(ValidationError):
        services.place_order(session=session, items=[line(menu["garba"])] * 31)
    with pytest.raises(ValidationError) as exc:
        services.place_order(session=session, items=[line(menu["garba"], quantity=21)])
    assert errors_of(exc)[0]["quantity"]


def test_dix_commandes_par_heure(menu, session):
    for _ in range(10):
        services.place_order(session=session, items=[line(menu["garba"])])
    with pytest.raises(ValidationError):
        services.place_order(session=session, items=[line(menu["garba"])])


def test_session_fermee(menu, session):
    services.close_session(session)
    with pytest.raises(ValidationError):
        services.place_order(session=session, items=[line(menu["garba"])])


def test_commande_au_comptoir(menu, staff):
    order = services.place_order(items=[line(menu["garba"])], created_by=staff["cashier"])
    assert (order.channel, order.session, order.created_by) == ("counter", None, staff["cashier"])


# --- advance / cancel ----------------------------------------------------------------------------

@pytest.fixture
def order(menu, session):
    return services.place_order(session=session, items=[line(menu["garba"])])


@pytest.mark.parametrize("start, role, allowed", [
    (S.RECEIVED, "kitchen", True), (S.RECEIVED, "waiter", False), (S.RECEIVED, "cashier", False),
    (S.PREPARING, "kitchen", True), (S.PREPARING, "waiter", False),
    (S.READY, "waiter", True), (S.READY, "cashier", True), (S.READY, "kitchen", False),
    (S.RECEIVED, "manager", True), (S.READY, "manager", True),
])
def test_advance_par_role(order, staff, start, role, allowed):
    Order.objects.filter(pk=order.pk).update(status=start)
    if allowed:
        advanced = services.advance(order, staff[role])
        assert advanced.status == services.NEXT_STATUS[start] and advanced.status_changed_by == staff[role]
    else:
        with pytest.raises(PermissionDenied):
            services.advance(order, staff[role])


def test_advance_horodatage_et_fin(order, staff):
    for field in ("accepted_at", "ready_at"):
        order = services.advance(order, staff["kitchen"])
        assert getattr(order, field)
    order = services.advance(order, staff["waiter"])
    assert order.status == S.SERVED and order.served_at
    with pytest.raises(ValidationError):
        services.advance(order, staff["manager"])


@pytest.mark.parametrize("role, allowed", [("manager", True), ("cashier", True), ("waiter", False), ("kitchen", False)])
def test_cancel_par_role(order, staff, role, allowed):
    if allowed:
        cancelled = services.cancel(order, staff[role], "Client parti")
        assert (cancelled.status, cancelled.cancel_reason) == (S.CANCELLED, "Client parti") and cancelled.cancelled_at
    else:
        with pytest.raises(PermissionDenied):
            services.cancel(order, staff[role], "Client parti")


def test_cancel_motif_obligatoire_et_commande_prete(order, staff):
    with pytest.raises(ValidationError):
        services.cancel(order, staff["cashier"], "  ")
    Order.objects.filter(pk=order.pk).update(status=S.READY)
    with pytest.raises(ValidationError):
        services.cancel(order, staff["cashier"], "Trop tard")


# --- request_service / complete_request ------------------------------------------------------

def test_une_demande_ouverte_par_type(session):
    first, created = services.request_service(session, "waiter")
    again, created_again = services.request_service(session, "waiter")
    assert created and not created_again and again == first
    session.refresh_from_db()
    assert session.status == TableSession.Status.OPEN


def test_addition_passe_la_session_en_addition_demandee(session):
    services.request_service(session, "bill")
    session.refresh_from_db()
    assert session.status == TableSession.Status.BILL_REQUESTED


def test_complete_request_puis_nouvelle_demande(session, staff):
    req, _ = services.request_service(session, "waiter")
    done = services.complete_request(req, staff["waiter"])
    assert (done.status, done.handled_by) == (ServiceRequest.Status.DONE, staff["waiter"]) and done.handled_at
    _, created = services.request_service(session, "waiter")
    assert created


def test_demande_sur_session_fermee(session):
    services.close_session(session)
    with pytest.raises(ValidationError):
        services.request_service(session, "waiter")
