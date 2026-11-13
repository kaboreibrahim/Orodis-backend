import pytest

from apps.menu import services
from apps.menu.models import Category, Dish, SubCategory

pytestmark = pytest.mark.django_db
MENU = "/api/v1/menu/"


def url(dish_id):
    return f"/api/v1/manage/dishes/{dish_id}/availability/"


@pytest.fixture
def dish(db):
    sub = SubCategory.objects.create(name="Sauces", category=Category.objects.create(name="Plats africains"))
    return Dish.objects.create(name="Kedjenou", price=4500, subcategory=sub)


def dish_names(api):
    return [d["name"] for c in api.get(MENU).json() for s in c["subcategories"] for d in s["dishes"]]


@pytest.mark.parametrize("role, expected", [
    ("manager", 200), ("cashier", 200), ("kitchen", 200), ("waiter", 403), (None, 401),
])
def test_roles(as_role, dish, role, expected):
    assert as_role(role).patch(url(dish.id), {"is_available": False}, format="json").status_code == expected


def test_rupture_retire_le_plat_de_la_carte(as_role, dish, django_capture_on_commit_callbacks):
    api = as_role("kitchen")
    assert dish_names(api) == ["Kedjenou"]  # carte mise en cache
    with django_capture_on_commit_callbacks(execute=True):
        r = api.patch(url(dish.id), {"is_available": False}, format="json")
    assert r.json() == {"id": dish.id, "name": "Kedjenou", "is_available": False}
    assert dish_names(api) == []  # le cache a été vidé

    with django_capture_on_commit_callbacks(execute=True):
        api.patch(url(dish.id), {"is_available": True}, format="json")
    assert dish_names(api) == ["Kedjenou"]


def test_nom_non_modifiable(as_role, dish):
    as_role("cashier").patch(url(dish.id), {"is_available": False, "name": "Autre"}, format="json")
    dish.refresh_from_db()
    assert (dish.name, dish.is_available) == ("Kedjenou", False)


@pytest.mark.parametrize("body", [{}, {"is_available": "peut-être"}])
def test_corps_invalide(as_role, dish, body):
    r = as_role("manager").patch(url(dish.id), body, format="json")
    assert r.status_code == 400 and r.json()["is_available"]


def test_plat_inconnu(as_role):
    assert as_role("manager").patch(url(999), {"is_available": False}, format="json").status_code == 404


def test_set_dish_availability(dish):
    assert services.set_dish_availability(dish, False).is_available is False
    dish.refresh_from_db()
    assert dish.is_available is False
    # Même valeur : rien n'est réenregistré
    updated = dish.updated_at
    assert services.set_dish_availability(dish, False).updated_at == updated


@pytest.mark.parametrize("role, expected", [
    ("manager", 200), ("cashier", 200), ("kitchen", 200), ("waiter", 403), (None, 401),
])
def test_liste_des_plats_roles(as_role, dish, role, expected):
    assert as_role(role).get("/api/v1/manage/dishes/").status_code == expected


def test_liste_des_plats_inclut_les_ruptures(as_role, dish):
    dish.is_available = False
    dish.save()
    r = as_role("kitchen").get("/api/v1/manage/dishes/")
    assert r.json() == [{"id": dish.id, "name": "Kedjenou", "category": "Plats africains",
                         "subcategory": "Sauces", "is_available": False}]
