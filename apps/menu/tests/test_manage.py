from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.menu.models import Category, Dish, Option, OptionGroup, SubCategory
from apps.orders import services as order_services

pytestmark = pytest.mark.django_db
BASE = "/api/v1/manage/menu/"


@pytest.fixture
def carte(db):
    plats = Category.objects.create(name="Plats africains")
    sauces = SubCategory.objects.create(name="Sauces", category=plats)
    grillades = SubCategory.objects.create(name="Grillades", category=plats, position=1)
    kedjenou = Dish.objects.create(name="Kedjenou", price=4500, subcategory=sauces)
    garba = Dish.objects.create(name="Garba", price=3500, subcategory=sauces, position=1)
    groupe = OptionGroup.objects.create(dish=kedjenou, name="Accompagnement", min_choices=1, max_choices=1)
    attieke = Option.objects.create(group=groupe, name="Attiéké")
    riz = Option.objects.create(group=groupe, name="Riz", position=1)
    return {"plats": plats, "sauces": sauces, "grillades": grillades, "kedjenou": kedjenou, "garba": garba,
            "groupe": groupe, "attieke": attieke, "riz": riz}


def photo(name="plat.png"):
    buffer = BytesIO()
    Image.new("RGB", (40, 30), "#810C1B").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@pytest.mark.parametrize("role, expected", [("manager", 200), ("cashier", 403), ("kitchen", 403), (None, 401)])
def test_carte_reservee_au_gerant(as_role, carte, role, expected):
    assert as_role(role).get(BASE).status_code == expected


def test_carte_complete_avec_plats_en_rupture_et_elements_masques(as_role, carte):
    carte["garba"].is_available = False
    carte["garba"].save()
    Category.objects.create(name="Boissons", is_active=False, position=1)
    data = as_role("manager").get(BASE).json()
    assert [(c["name"], c["is_active"]) for c in data] == [("Plats africains", True), ("Boissons", False)]
    sauces = data[0]["subcategories"][0]
    assert [(d["name"], d["is_available"]) for d in sauces["dishes"]] == [("Kedjenou", True), ("Garba", False)]
    assert [o["name"] for o in sauces["dishes"][0]["option_groups"][0]["options"]] == ["Attiéké", "Riz"]


def test_creer_categorie_sous_categorie_et_plat_a_la_fin(as_role, carte):
    api = as_role("manager")
    boissons = api.post(BASE + "categories/", {"name": "Boissons"}, format="json")
    assert boissons.status_code == 201 and boissons.json()["position"] == 1 and boissons.json()["slug"] == "boissons"
    jus = api.post(BASE + "subcategories/", {"name": "Jus", "category": boissons.json()["id"]}, format="json")
    assert jus.status_code == 201 and jus.json()["position"] == 0
    plat = api.post(BASE + "dishes/", {
        "name": "Sauce graine", "price": 4000, "subcategory": carte["sauces"].id, "description": "Avec du poisson fumé.",
        "option_groups": [{"name": "Piment", "min_choices": 0, "max_choices": 1,
                           "options": [{"name": "Doux"}, {"name": "Fort", "price_delta": 0}]}],
    }, format="json")
    assert plat.status_code == 201, plat.json()
    assert plat.json()["position"] == 2 and plat.json()["slug"] == "sauce-graine"
    assert [o["name"] for o in plat.json()["option_groups"][0]["options"]] == ["Doux", "Fort"]


def test_modifier_un_plat_remplace_ses_groupes_d_options(as_role, carte):
    api = as_role("manager")
    r = api.patch(f"{BASE}dishes/{carte['kedjenou'].id}/", {
        "price": 5000,
        "option_groups": [
            {"id": carte["groupe"].id, "name": "Accompagnement", "min_choices": 1, "max_choices": 2, "options": [
                {"id": carte["riz"].id, "name": "Riz blanc", "price_delta": 0},
                {"name": "Foutou banane", "price_delta": 500},
            ]},
            {"name": "Piment", "min_choices": 0, "max_choices": 1, "options": [{"name": "Fort"}]},
        ],
    }, format="json")
    assert r.status_code == 200, r.json()
    groups = r.json()["option_groups"]
    assert r.json()["price"] == 5000 and [g["name"] for g in groups] == ["Accompagnement", "Piment"]
    assert groups[0]["id"] == carte["groupe"].id and groups[0]["max_choices"] == 2
    assert [(o["id"] == carte["riz"].id, o["name"], o["price_delta"]) for o in groups[0]["options"]] == [
        (True, "Riz blanc", 0), (False, "Foutou banane", 500)]
    assert not Option.objects.filter(pk=carte["attieke"].pk).exists()  # absente de la liste : supprimée


def test_modifier_sans_option_groups_garde_les_options(as_role, carte):
    r = as_role("manager").patch(f"{BASE}dishes/{carte['kedjenou'].id}/", {"name": "Kedjenou de poulet"}, format="json")
    assert r.status_code == 200 and len(r.json()["option_groups"][0]["options"]) == 2


@pytest.mark.parametrize("payload, field", [
    ({"price": 4502}, "price"),
    ({"option_groups": [{"name": "Vide", "min_choices": 0, "max_choices": 1, "options": []}]}, "option_groups"),
    ({"option_groups": [{"name": "Trop", "min_choices": 2, "max_choices": 1, "options": [{"name": "A"}]}]}, "option_groups"),
])
def test_validation_du_plat(as_role, carte, payload, field):
    r = as_role("manager").patch(f"{BASE}dishes/{carte['kedjenou'].id}/", payload, format="json")
    assert r.status_code == 400 and field in r.json()


def test_mettre_en_rupture_previent_les_ecrans(as_role, carte, django_capture_on_commit_callbacks):
    from apps.orders.models import Event

    with django_capture_on_commit_callbacks(execute=True):
        as_role("manager").patch(f"{BASE}dishes/{carte['garba'].id}/", {"is_available": False}, format="json")
    assert Event.objects.filter(kind="dish.availability", data__dish_id=carte["garba"].id).exists()


def test_changer_l_ordre(as_role, carte):
    api = as_role("manager")
    ids = [carte["garba"].id, carte["kedjenou"].id]
    assert api.post(BASE + "reorder/", {"level": "dish", "ids": ids}, format="json").status_code == 204
    assert list(Dish.objects.filter(subcategory=carte["sauces"]).values_list("name", flat=True)) == ["Garba", "Kedjenou"]
    # liste incomplète : refusée
    assert api.post(BASE + "reorder/", {"level": "dish", "ids": [carte["garba"].id]}, format="json").status_code == 400
    assert api.post(BASE + "reorder/", {"level": "subcategory", "ids": [carte["grillades"].id, carte["sauces"].id]},
                    format="json").status_code == 204
    assert list(SubCategory.objects.values_list("name", flat=True)) == ["Grillades", "Sauces"]


def test_photo_convertie_en_webp_puis_retiree(as_role, carte, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    api = as_role("manager")
    url = f"{BASE}dishes/{carte['kedjenou'].id}/photo/"
    r = api.put(url, {"photo": photo()}, format="multipart")
    assert r.status_code == 200 and r.json()["photo"].endswith(".webp")
    assert (tmp_path / "menu/dishes/kedjenou.webp").exists()
    assert api.put(url, {"photo": SimpleUploadedFile("x.txt", b"pas une image")}, format="multipart").status_code == 400
    assert api.delete(url).json()["photo"] is None
    assert not (tmp_path / "menu/dishes/kedjenou.webp").exists()


def test_suppressions_protegees(as_role, carte):
    api = as_role("manager")
    r = api.delete(f"{BASE}categories/{carte['plats'].id}/")
    assert r.status_code == 400 and "sous-catégories" in r.json()["detail"]
    assert api.delete(f"{BASE}subcategories/{carte['grillades'].id}/").status_code == 204  # vide
    assert api.delete(f"{BASE}subcategories/{carte['sauces'].id}/").status_code == 400
    # un plat déjà commandé ne se supprime pas
    order_services.place_order(session=None, created_by=None, items=[
        {"dish_id": carte["garba"].id, "quantity": 1, "option_ids": [], "note": ""}])
    r = api.delete(f"{BASE}dishes/{carte['garba'].id}/")
    assert r.status_code == 400 and "rupture" in r.json()["detail"]
    assert api.delete(f"{BASE}dishes/{carte['kedjenou'].id}/").status_code == 204
