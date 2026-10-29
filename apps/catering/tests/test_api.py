import datetime as dt

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catering import services
from apps.catering.models import CateringFormula, QuoteRequest

pytestmark = pytest.mark.django_db
QUOTES_URL = "/api/v1/catering/quotes/"
MANAGE_URL = "/api/v1/manage/quotes/"
KEY = "cle-du-site"


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def make_user(django_user_model):
    return lambda role: django_user_model.objects.create_user(username=role, password="x", role=role)


def payload(buffet, **over):
    return {
        "event_type": "mariage", "event_date": str(timezone.localdate() + dt.timedelta(days=30)),
        "guests": 150, "place_type": "domicile", "place_detail": "Cocody", "formula": buffet.slug,
        "name": "Awa Koné", "whatsapp": "07 07 07 07 07", "email": "awa@example.com", **over,
    }


def test_get_formules(api, buffet):
    CateringFormula.objects.create(name="Ancienne", is_active=False)
    r = api.get("/api/v1/catering/formulas/")
    assert r.status_code == 200
    assert r.json() == [{
        "slug": "buffet", "name": "Buffet", "description": "", "price_from": None,
        "items": ["Entrées"], "is_highlighted": True,
    }]


def test_post_devis(api, restaurant, buffet):
    r = api.post(QUOTES_URL, payload(buffet), format="json")
    assert r.status_code == 201
    assert set(r.json()) == {"reference", "whatsapp_url"}
    assert r.json()["whatsapp_url"].startswith("https://wa.me/2250700000000?text=")


def test_post_devis_indecis(api, restaurant, buffet):
    r = api.post(QUOTES_URL, payload(buffet, formula="indecis"), format="json")
    assert r.status_code == 201
    assert QuoteRequest.objects.get().formula is None


@pytest.mark.parametrize("over, field, fragment", [
    ({"guests": 5}, "guests", "20 invités"),
    ({"event_date": "2020-01-01"}, "event_date", "déjà passée"),
    ({"formula": "inconnue"}, "formula", "Formule inconnue"),
    ({"whatsapp": "123"}, "whatsapp", "10 chiffres"),
    ({"event_type": "concert"}, "event_type", "n'est pas un choix valide"),
])
def test_post_devis_invalide(api, restaurant, buffet, over, field, fragment):
    r = api.post(QUOTES_URL, payload(buffet, **over), format="json")
    assert r.status_code == 400
    assert fragment in r.json()[field][0]


@override_settings(FRONTEND_API_KEY=KEY)
def test_throttle_par_ip_du_visiteur(api, restaurant, buffet):
    def post(ip):
        return api.post(QUOTES_URL, payload(buffet), format="json", HTTP_X_FRONTEND_KEY=KEY, HTTP_X_CLIENT_IP=ip)

    assert [post("41.0.0.1").status_code for _ in range(5)] == [201] * 5
    assert post("41.0.0.1").status_code == 429
    assert post("41.0.0.2").status_code == 201  # autre visiteur derrière le même serveur Next.js


def test_manage_liste_filtree(api, make_user, restaurant, quote_data):
    services.create_quote(**quote_data)
    won, _ = services.create_quote(**quote_data)
    services.update_quote(won, status="won")
    api.force_authenticate(make_user("cashier"))
    r = api.get(MANAGE_URL, {"status": "won"})
    assert r.status_code == 200
    assert [q["reference"] for q in r.json()["results"]] == [won.reference]


def test_manage_patch_statut_et_note(api, make_user, restaurant, quote_data):
    quote, _ = services.create_quote(**quote_data)
    api.force_authenticate(make_user("manager"))
    r = api.patch(f"{MANAGE_URL}{quote.pk}/",
                  {"status": "contacted", "internal_note": "Rappeler lundi", "name": "Autre"}, format="json")
    assert r.status_code == 200
    quote.refresh_from_db()
    assert (quote.status, quote.internal_note, quote.name) == ("contacted", "Rappeler lundi", "Awa Koné")


def test_manage_put_interdit(api, make_user, restaurant, quote_data):
    quote, _ = services.create_quote(**quote_data)
    api.force_authenticate(make_user("manager"))
    assert api.put(f"{MANAGE_URL}{quote.pk}/", {}, format="json").status_code == 405


@pytest.mark.parametrize("role, expected", [(None, 401), ("waiter", 403), ("kitchen", 403)])
def test_manage_acces_refuse(api, make_user, role, expected):
    if role:
        api.force_authenticate(make_user(role))
    assert api.get(MANAGE_URL).status_code == expected
