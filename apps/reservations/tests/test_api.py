import datetime as dt

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.core.models import DAYS
from apps.reservations import services
from apps.tables.models import Table, Zone

pytestmark = pytest.mark.django_db
AVAIL = "/api/v1/reservations/availability/"
CREATE = "/api/v1/reservations/"
MANAGE = "/api/v1/manage/reservations/"
KEY = "cle-du-site"


def body(day, **over):
    return {"date": day.isoformat(), "time": "12:00", "party_size": 4,
            "name": "Awa Koné", "phone": "07 07 07 07 07", "note": "Anniversaire", **over}


@pytest.fixture
def pending(restaurant, day):
    return services.create_reservation(date=day, time=dt.time(12, 0), party_size=4, name="Awa", phone="0707070707")


# --- GET /availability/ ---------------------------------------------------------------------

def test_availability_contrat(api, restaurant, day):
    r = api.get(AVAIL, {"date": day.isoformat(), "party": 4})
    data = r.json()
    assert r.status_code == 200
    assert (data["date"], data["party"], data["closed"], data["max_party"]) == (day.isoformat(), 4, False, 12)
    assert data["slots"][0] == {"time": "11:00", "available": True}


def test_availability_jour_ferme(api, restaurant, day):
    restaurant.opening_hours = {DAYS[(day.weekday() + 1) % 7]: [["11:00", "23:00"]]}
    restaurant.save()
    r = api.get(AVAIL, {"date": day.isoformat(), "party": 2})
    assert (r.json()["closed"], r.json()["slots"]) == (True, [])


@pytest.mark.parametrize("params, field", [
    ({"date": "2020-01-01", "party": 2}, "date"),
    ({"party": 2, "offset": 61}, "date"),
    ({"party": 13}, "party"),
    ({"party": 0}, "party"),
    ({"date": "pas-une-date", "party": 2}, "date"),
])
def test_availability_400(api, restaurant, day, params, field):
    params = dict(params)
    offset = params.pop("offset", None)
    params.setdefault("date", (timezone.localdate() + dt.timedelta(days=offset)).isoformat() if offset else day.isoformat())
    r = api.get(AVAIL, params)
    assert r.status_code == 400 and r.json()[field][0]


# --- POST /reservations/ --------------------------------------------------------------------

def test_post_reservation_contrat(api, restaurant, day):
    r = api.post(CREATE, body(day), format="json")
    assert r.status_code == 201
    assert r.json() == {"reference": f"R-{day:%d%m}-0001", "status": "pending",
                        "date": day.isoformat(), "time": "12:00", "party_size": 4}
    assert "Awa" not in r.content.decode() and "0707" not in r.content.decode()


def test_post_creneau_complet(api, restaurant, day):
    services.create_reservation(date=day, time=dt.time(12, 0), party_size=10, name="X", phone="0101010101")
    r = api.post(CREATE, body(day, party_size=1), format="json")
    assert r.status_code == 400
    assert r.json() == {"time": ["Ce créneau vient d'être complet, choisissez-en un autre."]}


def test_post_groupe_trop_grand(api, restaurant, day):
    r = api.post(CREATE, body(day, party_size=13), format="json")
    assert r.status_code == 400
    assert r.data["party_size"][0].code == "party_too_large"


@pytest.mark.parametrize("over, field", [({"phone": "123"}, "phone"), ({"time": "12h00"}, "time"), ({"name": ""}, "name")])
def test_post_invalide(api, restaurant, day, over, field):
    r = api.post(CREATE, body(day, **over), format="json")
    assert r.status_code == 400 and field in r.json()


@override_settings(FRONTEND_API_KEY=KEY)
def test_throttle_ip_du_visiteur_via_la_cle(api, restaurant, day):
    def post(ip):
        return api.post(CREATE, body(day, party_size=1), format="json", HTTP_X_FRONTEND_KEY=KEY, HTTP_X_CLIENT_IP=ip)

    assert [post("41.0.0.1").status_code for _ in range(5)] == [201] * 5
    assert post("41.0.0.1").status_code == 429
    assert post("41.0.0.2").status_code == 201  # autre visiteur derrière le même serveur Next.js


@override_settings(FRONTEND_API_KEY=KEY)
def test_throttle_cle_fausse_compte_l_ip_du_serveur(api, restaurant, day):
    codes = [
        api.post(CREATE, body(day, party_size=1), format="json",
                 HTTP_X_FRONTEND_KEY="fausse", HTTP_X_CLIENT_IP=f"41.0.0.{i}").status_code
        for i in range(6)
    ]
    assert codes == [201] * 5 + [429]  # X-Client-IP ignoré : tout compte pour REMOTE_ADDR


# --- /manage/reservations/ ------------------------------------------------------------------

def test_manage_liste_filtree(api, make_user, manager, restaurant, day, pending):
    other = services.create_reservation(date=day, time=dt.time(13, 0), party_size=2, name="B", phone="0101010101")
    services.refuse_reservation(other, manager, "Complet")
    api.force_authenticate(make_user("cashier"))
    r = api.get(MANAGE, {"date": day.isoformat(), "status": "pending"})
    assert r.status_code == 200
    assert [x["reference"] for x in r.json()["results"]] == [pending.reference]
    assert r.json()["results"][0]["phone"] == "+2250707070707"


def test_manage_confirm_avec_table(api, manager, pending):
    table = Table.objects.create(number=5, zone=Zone.objects.create(name="Salle"))
    api.force_authenticate(manager)
    r = api.post(f"{MANAGE}{pending.pk}/confirm/", {"table_id": table.pk}, format="json")
    assert r.status_code == 200
    assert (r.json()["reservation"]["status"], r.json()["reservation"]["table_number"]) == ("confirmed", 5)
    assert r.json()["whatsapp_url"].startswith("https://wa.me/2250707070707?text=")


def test_manage_refuse_motif_obligatoire(api, manager, pending):
    api.force_authenticate(manager)
    assert api.post(f"{MANAGE}{pending.pk}/refuse/", {}, format="json").status_code == 400
    r = api.post(f"{MANAGE}{pending.pk}/refuse/", {"reason": "Complet ce soir"}, format="json")
    assert r.status_code == 200 and r.json()["reservation"]["status"] == "refused"


@pytest.mark.parametrize("path, status, has_link", [
    ("cancel", "cancelled", True), ("no-show", "no_show", False), ("complete", "completed", False),
])
def test_manage_suite_du_cycle(api, manager, pending, path, status, has_link):
    services.confirm_reservation(pending, manager)
    api.force_authenticate(manager)
    r = api.post(f"{MANAGE}{pending.pk}/{path}/")
    assert r.status_code == 200 and r.json()["reservation"]["status"] == status
    assert (r.json()["whatsapp_url"] is not None) == has_link


def test_manage_transition_interdite(api, manager, pending):
    api.force_authenticate(manager)
    r = api.post(f"{MANAGE}{pending.pk}/cancel/")
    assert r.status_code == 400 and "status" in r.json()


def test_manage_saisie_telephone(api, manager, restaurant, day):
    api.force_authenticate(manager)
    r = api.post(MANAGE, body(day, source="phone"), format="json")
    assert r.status_code == 201
    assert (r.json()["reservation"]["status"], r.json()["reservation"]["source"]) == ("confirmed", "phone")
    assert r.json()["whatsapp_url"]


@pytest.mark.parametrize("role, expected", [(None, 401), ("kitchen", 403), ("waiter", 200), ("cashier", 200)])
def test_manage_acces_liste(api, make_user, role, expected):
    if role:
        api.force_authenticate(make_user(role))
    assert api.get(MANAGE).status_code == expected


def test_serveur_voit_le_jour_meme_en_lecture_seule(api, make_user, manager, restaurant, day, pending):
    today = services.create_reservation(date=timezone.localdate(), time=dt.time(11, 0), party_size=2,
                                        name="C", phone="0505050505", created_by=manager)
    api.force_authenticate(make_user("waiter"))
    assert [x["reference"] for x in api.get(MANAGE).json()["results"]] == [today.reference]
    assert api.get(f"{MANAGE}{pending.pk}/").status_code == 404
    assert api.post(f"{MANAGE}{pending.pk}/confirm/", {}, format="json").status_code == 403
