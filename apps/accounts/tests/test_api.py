import pytest

from apps.core.throttling import ScopedRateThrottle

pytestmark = pytest.mark.django_db
TOKEN = "/api/v1/auth/token/"
REFRESH = "/api/v1/auth/token/refresh/"
LOGOUT = "/api/v1/auth/logout/"
ME = "/api/v1/auth/me/"


def login(api, username="cashier", password="x"):
    return api.post(TOKEN, {"username": username, "password": password}, format="json")


@pytest.fixture
def cashier(make_user):
    return make_user("cashier", first_name="Awa", last_name="Koné")


# --- POST /auth/token/ ----------------------------------------------------------------------

def test_connexion_renvoie_acces_et_rafraichissement(api, cashier):
    r = login(api)
    assert r.status_code == 200
    assert set(r.json()) == {"access", "refresh"}


def test_connexion_mauvais_mot_de_passe(api, cashier):
    r = login(api, password="faux")
    assert r.status_code == 401 and r.json()["detail"]


def test_compte_desactive_refuse(api, cashier):
    cashier.is_active = False
    cashier.save()
    assert login(api).status_code == 401


def test_verrouillage_apres_5_echecs(api, cashier):
    for _ in range(5):
        login(api, password="faux")
    # django-axes bloque même le bon mot de passe
    assert login(api).status_code in (401, 403)
    assert "access" not in login(api).json()


def test_limite_de_connexions_par_minute(api, cashier, monkeypatch):
    # DRF lit les débits au chargement de la classe : on remplace le dictionnaire le temps du test
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {**ScopedRateThrottle.THROTTLE_RATES, "login": "2/min"})
    statuses = [login(api).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]


# --- GET /auth/me/ --------------------------------------------------------------------------

@pytest.mark.parametrize("role, label", [
    ("manager", "Gérant"), ("cashier", "Caisse"), ("waiter", "Serveur"), ("kitchen", "Cuisine"),
])
def test_me_chaque_role(api, make_user, role, label):
    user = make_user(role)
    access = login(api, username=user.username).json()["access"]
    r = api.get(ME, HTTP_AUTHORIZATION=f"Bearer {access}")
    assert r.status_code == 200
    assert r.json() == {"id": user.id, "username": role, "name": role, "role": role, "role_display": label}


def test_me_nom_complet(api, cashier):
    access = login(api).json()["access"]
    assert api.get(ME, HTTP_AUTHORIZATION=f"Bearer {access}").json()["name"] == "Awa Koné"


def test_me_sans_jeton(api):
    assert api.get(ME).status_code == 401


def test_me_jeton_invalide(api):
    assert api.get(ME, HTTP_AUTHORIZATION="Bearer pas-un-jeton").status_code == 401


# --- POST /auth/token/refresh/ et /auth/logout/ --------------------------------------------

def test_rafraichissement_tourne_et_bloque_l_ancien(api, cashier):
    refresh = login(api).json()["refresh"]
    r = api.post(REFRESH, {"refresh": refresh}, format="json")
    assert r.status_code == 200 and set(r.json()) == {"access", "refresh"}
    assert r.json()["refresh"] != refresh
    # L'ancien jeton est en liste noire après la rotation
    assert api.post(REFRESH, {"refresh": refresh}, format="json").status_code == 401


def test_deconnexion_met_le_jeton_en_liste_noire(api, cashier):
    refresh = login(api).json()["refresh"]
    assert api.post(LOGOUT, {"refresh": refresh}, format="json").status_code == 204
    assert api.post(REFRESH, {"refresh": refresh}, format="json").status_code == 401


@pytest.mark.parametrize("body", [{"refresh": "pas-un-jeton"}, {}])
def test_deconnexion_jeton_invalide(api, body):
    r = api.post(LOGOUT, body, format="json")
    assert r.status_code == 400 and r.json()["refresh"]


def test_deconnexion_deux_fois(api, cashier):
    refresh = login(api).json()["refresh"]
    api.post(LOGOUT, {"refresh": refresh}, format="json")
    assert api.post(LOGOUT, {"refresh": refresh}, format="json").status_code == 400
