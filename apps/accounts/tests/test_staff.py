import re

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User

pytestmark = pytest.mark.django_db
STAFF = "/api/v1/manage/staff/"
TOKEN = "/api/v1/auth/token/"
PASSWORD = "/api/v1/auth/password/"


@pytest.fixture
def gerant(make_user):
    return make_user("manager", first_name="Awa")


@pytest.fixture
def api_gerant(gerant):
    client = APIClient()
    client.force_authenticate(gerant)
    return client


@pytest.fixture
def serveur(make_user):
    return make_user("waiter", first_name="Koffi", last_name="Yao")


@pytest.mark.parametrize("role, expected", [("manager", 200), ("cashier", 403), ("waiter", 403), ("kitchen", 403), (None, 401)])
def test_liste_reservee_au_gerant(as_role, role, expected):
    assert as_role(role).get(STAFF).status_code == expected


def test_liste_par_role_puis_inactifs(api_gerant, make_user):
    make_user("kitchen", first_name="Moussa")
    make_user("cashier", first_name="Fanta", is_active=False)
    data = api_gerant.get(STAFF).json()
    assert [(m["username"], m["role_display"], m["is_active"]) for m in data] == [
        ("manager", "Gérant", True), ("kitchen", "Cuisine", True), ("cashier", "Caisse", False)]
    assert "password" not in data[0]


def test_creation_avec_mot_de_passe_provisoire(api_gerant):
    r = api_gerant.post(STAFF, {"username": "Fanta.Kone", "first_name": "Fanta", "last_name": "Koné", "role": "cashier",
                                "phone": "07 00 00 00 00"}, format="json")
    assert r.status_code == 201, r.json()
    data = r.json()
    assert data["username"] == "fanta.kone" and data["role"] == "cashier" and data["must_change_password"] is True
    assert re.fullmatch(r"[a-z2-9]{3}-[a-z2-9]{3}-[a-z2-9]{3}", data["temporary_password"])
    # le mot de passe provisoire permet de se connecter
    assert APIClient().post(TOKEN, {"username": "fanta.kone", "password": data["temporary_password"]}, format="json").status_code == 200
    # il n'est plus jamais renvoyé
    assert "temporary_password" not in api_gerant.get(STAFF).json()[-1]


def test_creation_avec_mot_de_passe_choisi(api_gerant):
    r = api_gerant.post(STAFF, {"username": "moussa", "first_name": "Moussa", "role": "kitchen", "password": "Attieke-2026!"}, format="json")
    assert r.status_code == 201 and r.json()["temporary_password"] is None
    assert User.objects.get(username="moussa").check_password("Attieke-2026!")


@pytest.mark.parametrize("payload, field", [
    ({"username": "manager", "first_name": "X", "role": "waiter"}, "username"),        # déjà pris
    ({"username": "MANAGER", "first_name": "X", "role": "waiter"}, "username"),        # déjà pris, autre casse
    ({"username": "jé", "first_name": "X", "role": "waiter"}, "username"),             # trop court, accent
    ({"username": "jean", "first_name": " ", "role": "waiter"}, "first_name"),
    ({"username": "jean", "first_name": "Jean", "role": "chef"}, "role"),
    ({"username": "jean", "first_name": "Jean", "role": "waiter", "password": "12345678"}, "non_field_errors"),
])
def test_creation_refusee(api_gerant, payload, field):
    r = api_gerant.post(STAFF, payload, format="json")
    assert r.status_code == 400 and field in r.json(), r.json()


def test_changer_le_role_et_les_coordonnees(api_gerant, serveur):
    r = api_gerant.patch(f"{STAFF}{serveur.id}/", {"role": "cashier", "phone": "01 02 03 04 05"}, format="json")
    assert r.status_code == 200 and r.json()["role_display"] == "Caisse"
    serveur.refresh_from_db()
    assert serveur.role == "cashier" and serveur.phone == "01 02 03 04 05"


def test_desactiver_ferme_les_sessions(api_gerant, serveur):
    refresh = RefreshToken.for_user(serveur)
    r = api_gerant.patch(f"{STAFF}{serveur.id}/", {"is_active": False}, format="json")
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert BlacklistedToken.objects.filter(token__jti=refresh["jti"]).exists()
    assert APIClient().post("/api/v1/auth/token/refresh/", {"refresh": str(refresh)}, format="json").status_code == 401
    assert APIClient().post(TOKEN, {"username": "waiter", "password": "x"}, format="json").status_code == 401


def test_garde_fous_sur_son_propre_compte(api_gerant, gerant, make_user):
    make_user("cashier")
    r = api_gerant.patch(f"{STAFF}{gerant.id}/", {"is_active": False}, format="json")
    assert r.status_code == 400 and "propre compte" in r.json()["is_active"][0]
    r = api_gerant.patch(f"{STAFF}{gerant.id}/", {"role": "cashier"}, format="json")
    assert r.status_code == 400 and "propre rôle" in r.json()["role"][0]
    # son nom, lui, se modifie
    assert api_gerant.patch(f"{STAFF}{gerant.id}/", {"last_name": "Diallo"}, format="json").status_code == 200


def test_il_reste_toujours_un_gerant_actif(api_gerant, gerant, django_user_model):
    # deux gérants : on peut en rétrograder un
    adjoint = django_user_model.objects.create_user(username="adjoint", password="x", role="manager")
    assert api_gerant.patch(f"{STAFF}{adjoint.id}/", {"role": "waiter"}, format="json").status_code == 200
    # le propriétaire (superutilisateur, sans rôle de gérant) ne peut pas retirer le dernier gérant actif
    owner = django_user_model.objects.create_superuser(username="proprio", password="x", role="waiter")
    client = APIClient()
    client.force_authenticate(owner)
    for change in ({"role": "cashier"}, {"is_active": False}):
        r = client.patch(f"{STAFF}{gerant.id}/", change, format="json")
        assert r.status_code == 400 and "au moins un gérant" in r.json()["role"][0]


def test_compte_proprietaire_protege(api_gerant, django_user_model):
    owner = django_user_model.objects.create_superuser(username="proprio", password="x")
    r = api_gerant.patch(f"{STAFF}{owner.id}/", {"is_active": False}, format="json")
    assert r.status_code == 403
    assert api_gerant.post(f"{STAFF}{owner.id}/reset-password/").status_code == 403
    assert next(m for m in api_gerant.get(STAFF).json() if m["username"] == "proprio")["is_owner"] is True


def test_mot_de_passe_provisoire_ferme_les_sessions(api_gerant, serveur):
    refresh = RefreshToken.for_user(serveur)
    r = api_gerant.post(f"{STAFF}{serveur.id}/reset-password/")
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    serveur.refresh_from_db()
    assert serveur.check_password(r.json()["temporary_password"]) and not serveur.check_password("x")
    assert BlacklistedToken.objects.filter(token__jti=refresh["jti"]).exists()
    # pas pour soi-même
    me = User.objects.get(username="manager")
    assert api_gerant.post(f"{STAFF}{me.id}/reset-password/").status_code == 400


def test_pas_de_suppression(api_gerant, serveur):
    assert api_gerant.delete(f"{STAFF}{serveur.id}/").status_code == 405


# --- Changer son propre mot de passe ------------------------------------------------------------

def test_changer_son_mot_de_passe(serveur):
    serveur.must_change_password = True
    serveur.save()
    client = APIClient()
    client.force_authenticate(serveur)
    assert client.get("/api/v1/auth/me/").json()["must_change_password"] is True
    r = client.post(PASSWORD, {"current_password": "x", "new_password": "Garba-du-soir-7"}, format="json")
    assert r.status_code == 200 and r.json()["must_change_password"] is False
    serveur.refresh_from_db()
    assert serveur.check_password("Garba-du-soir-7")


@pytest.mark.parametrize("payload, field", [
    ({"current_password": "faux", "new_password": "Garba-du-soir-7"}, "current_password"),
    ({"current_password": "x", "new_password": "x"}, "new_password"),
    ({"current_password": "x", "new_password": "password"}, "non_field_errors"),
])
def test_changer_son_mot_de_passe_refuse(serveur, payload, field):
    client = APIClient()
    client.force_authenticate(serveur)
    r = client.post(PASSWORD, payload, format="json")
    assert r.status_code == 400 and field in r.json(), r.json()
