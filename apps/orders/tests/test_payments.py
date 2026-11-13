import pytest
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.orders import events, printing, services
from apps.orders.models import Order, ServiceRequest, TableSession
from apps.payments import providers

from .conftest import line

pytestmark = pytest.mark.django_db
S = Order.Status


@pytest.fixture
def two_orders(menu, session):
    """Addition de la table 5 : 3 500 F + 9 000 F (kedjenou ×2 à l'attiéké)."""
    a = services.place_order(session=session, items=[line(menu["garba"])])
    b = services.place_order(session=session, items=[line(menu["kedjenou"], menu["attieke"], quantity=2)])
    return a, b


def staff_api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


# --- pay -------------------------------------------------------------------------------------

def test_addition_complete_ferme_la_session(two_orders, session, staff):
    services.request_service(session, "bill")
    services.request_service(session, "waiter")
    receipt = services.pay(session, "cash", "", staff["cashier"])
    session.refresh_from_db()
    assert receipt.total == 12500 and receipt.reference.startswith("R-") and receipt.cashier == staff["cashier"]
    assert sorted(o.number for o in receipt.orders.all()) == sorted(o.number for o in two_orders)
    assert session.status == TableSession.Status.CLOSED and session.closed_by == staff["cashier"]
    assert not session.requests.filter(status=ServiceRequest.Status.OPEN).exists()


def test_annulee_jamais_comptee(two_orders, session, staff):
    services.cancel(two_orders[1], staff["cashier"], "Erreur")
    assert services.pay(session, "cash", "", staff["cashier"]).total == 3500


def test_paiement_partiel_puis_le_reste(two_orders, session, staff):
    a, b = two_orders
    first = services.pay(session, "wave", "W-1", staff["cashier"], order_ids=[a.id])
    session.refresh_from_db()
    assert first.total == 3500 and not session.is_closed
    second = services.pay(session, "orange_money", "OM-2", staff["cashier"])
    session.refresh_from_db()
    assert second.total == 9000 and second.number == first.number + 1 and session.is_closed


def test_commande_deja_payee_ou_d_une_autre_table(two_orders, session, other_table, menu, staff):
    a, _ = two_orders
    services.pay(session, "cash", "", staff["cashier"], order_ids=[a.id])
    other = services.place_order(session=services.open_session(str(other_table.qr_token)), items=[line(menu["garba"])])
    for ids in ([a.id], [other.id]):
        with pytest.raises(ValidationError) as exc:
            services.pay(session, "cash", "", staff["cashier"], order_ids=ids)
        assert "order_ids" in exc.value.detail


@pytest.mark.parametrize("method, ref, ok", [
    ("wave", "", False), ("orange_money", "  ", False), ("mtn_momo", "MTN-9", True), ("cash", "", True),
])
def test_reference_obligatoire_pour_le_mobile_money(two_orders, session, staff, method, ref, ok):
    if ok:
        assert services.pay(session, method, ref, staff["cashier"]).transaction_ref == ref.strip()
    else:
        with pytest.raises(ValidationError) as exc:
            services.pay(session, method, ref, staff["cashier"])
        assert "transaction_ref" in exc.value.detail


@pytest.mark.parametrize("role", ["waiter", "kitchen"])
def test_seuls_caisse_et_gerant_encaissent(two_orders, session, staff, role):
    with pytest.raises(PermissionDenied):
        services.pay(session, "cash", "", staff[role])


def test_session_fermee_ou_rien_a_payer(session, staff):
    with pytest.raises(ValidationError):
        services.pay(session, "cash", "", staff["cashier"])  # aucune commande
    services.close_session(session)
    with pytest.raises(ValidationError):
        services.pay(session, "cash", "", staff["cashier"])


def test_paiement_non_confirme_ne_cree_rien(two_orders, session, staff, monkeypatch):
    monkeypatch.setattr(providers.ManualProvider, "verify", lambda self, ref: providers.PaymentStatus.PENDING)
    with pytest.raises(ValidationError):
        services.pay(session, "cash", "", staff["cashier"])
    assert not Order.objects.filter(receipt__isnull=False).exists()


def test_evenement_session_paid(two_orders, session, staff, monkeypatch, django_capture_on_commit_callbacks):
    sent = []
    monkeypatch.setattr(events, "session_paid", lambda s, reference: sent.append((s.pk, reference)))
    with django_capture_on_commit_callbacks(execute=True):
        receipt = services.pay(session, "cash", "", staff["cashier"])
    assert sent == [(session.pk, receipt.reference)]


# --- pay_order (comptoir) ----------------------------------------------------------------------

def test_commande_au_comptoir(menu, staff):
    order = services.place_order(items=[line(menu["garba"])], created_by=staff["cashier"])
    receipt = services.pay_order(order, "cash", "", staff["cashier"])
    assert receipt.session is None and receipt.total == 3500
    with pytest.raises(ValidationError):
        services.pay_order(order, "cash", "", staff["cashier"])  # déjà payée


def test_commande_de_table_refusee_au_comptoir(two_orders, staff):
    with pytest.raises(ValidationError):
        services.pay_order(two_orders[0], "cash", "", staff["cashier"])


# --- Fournisseur et impression ----------------------------------------------------------------

def test_fournisseur_manuel_par_defaut():
    provider = providers.get_provider()
    assert provider.code == "manual" and provider.verify("x") == providers.PaymentStatus.PAID


@pytest.mark.parametrize("amount, words", [
    (8000, "huit mille"), (13500, "treize mille cinq cents"), (71, "soixante et onze"), (80, "quatre-vingts"),
    (81, "quatre-vingt-un"), (280, "deux cent quatre-vingts"), (200000, "deux cent mille"),
    (21000, "vingt et un mille"), (1250000, "un million deux cent cinquante mille"),
])
def test_montant_en_lettres(amount, words):
    assert printing.amount_in_words(amount) == words


@pytest.mark.parametrize("raw", ["0584603011", "2250584603011", "+225 05 84 60 30 11"])
def test_telephone(raw):
    assert printing.phone(raw).replace(" ", " ") == "+225 05 84 60 30 11"


def test_reçu_pdf_une_puis_deux_pages(menu, session, staff):
    services.place_order(session=session, items=[line(menu["garba"])])
    short = services.pay(session, "cash", "", staff["cashier"])
    assert printing.receipt_pdf(short).count(b"/Type /Page\n") == 1
    long_session = services.open_session(str(session.table.qr_token))
    services.place_order(session=long_session, items=[line(menu["garba"]) for _ in range(14)])
    long = services.pay(long_session, "cash", "", staff["cashier"])
    assert printing.receipt_pdf(long).count(b"/Type /Page\n") == 2


# --- Routes -------------------------------------------------------------------------------------

def test_encaisser_par_l_api(two_orders, session, staff):
    url = f"/api/v1/manage/sessions/{session.id}/pay/"
    assert staff_api(staff["waiter"]).post(url, {"method": "cash"}, format="json").status_code == 403
    bad = staff_api(staff["cashier"]).post(url, {"method": "wave"}, format="json")
    assert bad.status_code == 400 and bad.json()["transaction_ref"]
    r = staff_api(staff["cashier"]).post(url, {"method": "wave", "transaction_ref": "W-77"}, format="json")
    data = r.json()
    assert r.status_code == 201
    assert (data["total"], data["method_display"], data["table_number"], data["cashier"]) == (12500, "Wave", 5, "cashier")
    assert data["reference"] == f"R-{data['number']:06d}" and len(data["orders"]) == 2


def test_encaisser_au_comptoir_par_l_api(menu, staff):
    order = services.place_order(items=[line(menu["garba"])], created_by=staff["cashier"])
    r = staff_api(staff["cashier"]).post(f"/api/v1/manage/orders/{order.id}/pay/", {"method": "cash"}, format="json")
    assert r.status_code == 201 and r.json()["table_number"] is None


def test_lire_un_recu_personnel(two_orders, session, staff):
    receipt = services.pay(session, "cash", "", staff["cashier"])
    base = f"/api/v1/manage/receipts/{receipt.number}"
    assert staff_api(staff["manager"]).get(f"{base}/").json()["reference"] == receipt.reference
    assert staff_api(staff["kitchen"]).get(f"{base}/").status_code == 403
    pdf = staff_api(staff["cashier"]).get(f"{base}.pdf")
    assert pdf["Content-Type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert f'recu-{receipt.reference}.pdf' in pdf["Content-Disposition"]


def test_le_telephone_voit_le_numero_du_recu(two_orders, session, phone, staff):
    order = two_orders[0]
    url = f"/api/v1/table/orders/{order.number}/"
    assert phone.get(url).json()["receipt_number"] is None
    receipt = services.pay(session, "cash", "", staff["cashier"])
    assert phone.get(url).json()["receipt_number"] == receipt.number  # session fermée : toujours lisible


def test_recu_de_la_table_seulement(two_orders, session, phone, other_table, staff):
    receipt = services.pay(session, "cash", "", staff["cashier"])
    base = f"/api/v1/table/receipts/{receipt.number}"
    assert phone.get(f"{base}/").status_code == 200   # session fermée : le reçu reste lisible
    assert phone.get(f"{base}.pdf").content.startswith(b"%PDF")
    other = APIClient()
    other.credentials(HTTP_X_SESSION_TOKEN=services.open_session(str(other_table.qr_token)).token)
    assert other.get(f"{base}/").status_code == 404 and other.get(f"{base}.pdf").status_code == 404


def test_le_personnel_voit_le_numero_du_recu(two_orders, session, staff):
    api = staff_api(staff["cashier"])
    numbers = lambda: {o["number"]: o["receipt_number"] for o in api.get("/api/v1/manage/orders/").json()["results"]}
    assert set(numbers().values()) == {None}
    receipt = services.pay(session, "wave", "W-1", staff["cashier"])
    assert set(numbers().values()) == {receipt.number}


def test_recu_personnel_avec_mentions_legales(two_orders, session, staff):
    from apps.core.models import RestaurantSettings

    rs = RestaurantSettings.load()
    rs.rccm, rs.ncc = "CI-ABJ-2026-B-123", "2600001A"
    rs.save()
    receipt = services.pay(session, "cash", "", staff["cashier"])
    legal = staff_api(staff["manager"]).get(f"/api/v1/manage/receipts/{receipt.number}/").json()["legal"]
    assert legal == {"rccm": "CI-ABJ-2026-B-123", "ncc": "2600001A", "vat_rate": None}
