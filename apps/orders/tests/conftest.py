import pytest
from rest_framework.test import APIClient

from apps.menu.models import Category, Dish, Option, OptionGroup, SubCategory
from apps.orders import services
from apps.tables.models import Table, Zone


@pytest.fixture
def menu(db):
    """Kedjenou 4 500 F (accompagnement obligatoire : attiéké inclus ou foutou +500 ; piment facultatif), garba 3 500 F."""
    sub = SubCategory.objects.create(name="Sauces", category=Category.objects.create(name="Plats africains"))
    kedjenou = Dish.objects.create(name="Kedjenou de poulet", price=4500, prep_minutes=20, subcategory=sub)
    acc = OptionGroup.objects.create(dish=kedjenou, name="Accompagnement", min_choices=1, max_choices=1, position=0)
    piment = OptionGroup.objects.create(dish=kedjenou, name="Piment", min_choices=0, max_choices=1, position=1)
    garba = Dish.objects.create(name="Garba spécial", price=3500, prep_minutes=10, subcategory=sub)
    return {
        "kedjenou": kedjenou, "garba": garba,
        "attieke": Option.objects.create(group=acc, name="Attiéké"),
        "foutou": Option.objects.create(group=acc, name="Foutou", price_delta=500),
        "doux": Option.objects.create(group=piment, name="Piment doux"),
        "garba_option": Option.objects.create(
            group=OptionGroup.objects.create(dish=garba, name="Poisson", max_choices=1), name="Thon"),
    }


@pytest.fixture
def table(db):
    return Table.objects.create(number=5, zone=Zone.objects.create(name="Salle"))


@pytest.fixture
def other_table(table):
    return Table.objects.create(number=6, zone=table.zone)


@pytest.fixture
def session(table):
    return services.open_session(str(table.qr_token))


@pytest.fixture
def phone(session):
    """Le téléphone de la table 5 : client API avec son X-Session-Token."""
    client = APIClient()
    client.credentials(HTTP_X_SESSION_TOKEN=session.token)
    return client


@pytest.fixture
def staff(make_user):
    return {role: make_user(role) for role in ("manager", "cashier", "waiter", "kitchen")}


def line(dish, *options, quantity=1, note=""):
    return {"dish_id": dish.id, "quantity": quantity, "option_ids": [o.id for o in options], "note": note}
