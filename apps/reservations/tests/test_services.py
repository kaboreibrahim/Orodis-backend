import datetime as dt
import threading
from urllib.parse import unquote

import pytest
from django.db import connection
from django.utils import formats, timezone
from rest_framework.exceptions import ValidationError

from apps.core.models import DAYS
from apps.core.utils import normalize_ci_phone
from apps.reservations import services
from apps.reservations.models import Reservation
from apps.tables.models import Table, Zone

pytestmark = pytest.mark.django_db
NOON = dt.time(12, 0)
FULL = "Ce créneau vient d'être complet, choisissez-en un autre."


def book(day, t=NOON, party=2, **kwargs):
    return services.create_reservation(date=day, time=t, party_size=party, name="Awa", phone="07 07 07 07 07", **kwargs)


def at(day, hhmm):
    return timezone.make_aware(dt.datetime.combine(day, dt.time.fromisoformat(hhmm)))


# --- available_slots ------------------------------------------------------------------------

def test_creneaux_du_jour(restaurant, day):
    data = services.available_slots(day, 2)
    times = [s["time"] for s in data["slots"]]
    assert (data["closed"], data["max_party"]) == (False, 12)
    assert times[0] == dt.time(11, 0)
    assert times[-1] == dt.time(22, 0)  # dernier créneau 60 min avant 23:00
    assert len(times) == 23 and all(s["available"] for s in data["slots"])


def test_jour_ferme(restaurant, day):
    restaurant.opening_hours = {d: [["11:00", "23:00"]] for d in DAYS if d != DAYS[day.weekday()]}
    restaurant.save()
    data = services.available_slots(day, 2)
    assert data["closed"] is True and data["slots"] == []


def test_creneau_passe(restaurant):
    today = timezone.localdate()
    now = at(today, "15:10")
    slots = {s["time"]: s["available"] for s in services.available_slots(today, 2, now=now)["slots"]}
    assert slots[dt.time(15, 0)] is False
    assert slots[dt.time(15, 30)] is True
    with pytest.raises(ValidationError) as exc:
        book(today, dt.time(15, 0), now=now)
    assert exc.value.detail["time"][0] == "Ce créneau est déjà passé."


def test_creneau_complet(restaurant, day):
    book(day, party=8)  # 8 couverts sur 10
    assert {s["time"]: s["available"] for s in services.available_slots(day, 2)["slots"]}[NOON] is True
    assert {s["time"]: s["available"] for s in services.available_slots(day, 3)["slots"]}[NOON] is False
    with pytest.raises(ValidationError) as exc:
        book(day, party=3)
    assert exc.value.detail["time"][0] == FULL


def test_refus_libere_le_creneau(restaurant, day, manager):
    full = book(day, party=10)
    services.refuse_reservation(full, manager, "Fermeture exceptionnelle")
    assert book(day, party=10).status == "pending"


def test_groupe_trop_grand(restaurant, day):
    with pytest.raises(ValidationError) as exc:
        services.available_slots(day, 13)
    assert exc.value.get_codes() == {"party": ["party_too_large"]}
    with pytest.raises(ValidationError) as exc:
        book(day, party=13)
    assert exc.value.get_codes() == {"party_size": ["party_too_large"]}
    assert "Traiteur" in str(exc.value.detail["party_size"][0])


@pytest.mark.parametrize("offset", [-1, 61])
def test_date_hors_fenetre(restaurant, offset):
    with pytest.raises(ValidationError) as exc:
        services.available_slots(timezone.localdate() + dt.timedelta(days=offset), 2)
    assert "date" in exc.value.detail


def test_creneau_hors_grille(restaurant, day):
    with pytest.raises(ValidationError) as exc:
        book(day, dt.time(12, 15))
    assert "n'est pas proposé" in str(exc.value.detail["time"][0])


# --- create_reservation ---------------------------------------------------------------------

def test_reference_telephone_et_statut(restaurant, day):
    first, second = book(day), book(day, dt.time(13, 0))
    assert first.reference == f"R-{day:%d%m}-0001"
    assert second.reference == f"R-{day:%d%m}-0002"
    assert (first.phone, first.status, first.source) == ("+2250707070707", "pending", "site")


def test_saisie_par_le_personnel_confirmee_et_forcee(restaurant, day, manager):
    book(day, party=10)  # créneau complet
    r = book(day, party=15, created_by=manager, source="phone")  # complet et au-delà du maximum
    assert (r.status, r.source, r.handled_by) == ("confirmed", "phone", manager)


@pytest.mark.django_db(transaction=True)
def test_deux_reservations_simultanees(restaurant, day):
    """6 + 6 > 10 couverts : une seule des deux demandes lancées en même temps doit passer."""
    barrier, results = threading.Barrier(2), []

    def worker():
        try:
            barrier.wait()
            book(day, party=6)
            results.append("ok")
        except ValidationError as exc:
            results.append(str(exc.detail["time"][0]))
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [FULL, "ok"]
    assert Reservation.objects.count() == 1


# --- Cycle de vie ---------------------------------------------------------------------------

ACTIONS = {
    "confirmed": lambda r, u: services.confirm_reservation(r, u),
    "refused": lambda r, u: services.refuse_reservation(r, u, "Complet ce soir"),
    "cancelled": services.cancel_reservation,
    "completed": services.complete_reservation,
    "no_show": services.mark_no_show,
}
ALLOWED = [("pending", "confirmed"), ("pending", "refused"),
           ("confirmed", "cancelled"), ("confirmed", "completed"), ("confirmed", "no_show")]
FORBIDDEN = [(a, b) for a in Reservation.Status.values for b in ACTIONS if (a, b) not in ALLOWED]


@pytest.mark.parametrize("start, target", ALLOWED)
def test_transition_autorisee(restaurant, day, manager, start, target):
    r = book(day)
    Reservation.objects.filter(pk=r.pk).update(status=start)
    r, link = ACTIONS[target](r, manager)
    assert (r.status, r.handled_by) == (target, manager) and r.handled_at
    assert (link is not None) == (target in ("confirmed", "refused", "cancelled"))


@pytest.mark.parametrize("start, target", FORBIDDEN)
def test_transition_interdite(restaurant, day, manager, start, target):
    r = book(day)
    Reservation.objects.filter(pk=r.pk).update(status=start)
    with pytest.raises(ValidationError) as exc:
        ACTIONS[target](r, manager)
    assert exc.value.get_codes() == {"status": ["invalid_transition"]}
    r.refresh_from_db()
    assert r.status == start


def test_confirmation_avec_table(restaurant, day, manager):
    table = Table.objects.create(number=5, zone=Zone.objects.create(name="Salle"))
    r, _ = services.confirm_reservation(book(day), manager, table=table)
    assert r.table == table


def test_table_desactivee_refusee(restaurant, day, manager):
    table = Table.objects.create(number=5, zone=Zone.objects.create(name="Salle"), is_active=False)
    with pytest.raises(ValidationError) as exc:
        services.confirm_reservation(book(day), manager, table=table)
    assert "table_id" in exc.value.detail


def test_refus_sans_motif(restaurant, day, manager):
    with pytest.raises(ValidationError) as exc:
        services.refuse_reservation(book(day), manager, "  ")
    assert "reason" in exc.value.detail


def test_notify_lien_whatsapp(restaurant, day, manager):
    r, link = services.confirm_reservation(book(day, party=4), manager)
    assert link.startswith("https://wa.me/2250707070707?text=")
    text = unquote(link.split("text=", 1)[1])
    for fragment in ("Bonjour Awa", "12h00", "4 personnes", r.reference, formats.date_format(day, "l j F")):
        assert fragment in text
    assert services.notify(r, "completed") is None


# --- Téléphone ------------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "0707070707", "07 07 07 07 07", "07.07.07.07.07", "+225 07 07 07 07 07", "002250707070707", "2250707070707",
])
def test_telephone_normalise(raw):
    assert normalize_ci_phone(raw) == "+2250707070707"


@pytest.mark.parametrize("raw", ["", "070707", "07070707070", "+33612345678", "abcdefghij"])
def test_telephone_invalide(raw):
    with pytest.raises(ValidationError):
        normalize_ci_phone(raw)
