import pytest

from apps.tables.models import Table, Zone

pytestmark = pytest.mark.django_db
ZONES = "/api/v1/manage/zones/"
TABLES = "/api/v1/manage/tables/"
SHEET = "/api/v1/manage/tables/qr-sheet.pdf"
ROLES = [("manager", 200), ("cashier", 403), ("waiter", 403), ("kitchen", 403), (None, 401)]


@pytest.fixture
def salle(db):
    return Zone.objects.create(name="Salle", position=1)


@pytest.fixture
def table(salle):
    return Table.objects.create(number=5, zone=salle, seats=4)


def pages(pdf):
    return pdf.count(b"/Type /Page\n") or pdf.count(b"/Type /Page ")


# --- Rôles : chaque route est réservée au gérant ---------------------------------------------

@pytest.mark.parametrize("role, expected", ROLES)
@pytest.mark.parametrize("url", [ZONES, TABLES, f"{TABLES}{{id}}/", f"{TABLES}{{id}}/qr.png", SHEET])
def test_lecture_reservee_au_gerant(as_role, table, url, role, expected):
    assert as_role(role).get(url.format(id=table.id)).status_code == expected


@pytest.mark.parametrize("role, expected", [(r, 201 if s == 200 else s) for r, s in ROLES])
def test_creation_reservee_au_gerant(as_role, salle, role, expected):
    r = as_role(role).post(TABLES, {"number": 9, "zone": salle.id}, format="json")
    assert r.status_code == expected


@pytest.mark.parametrize("role, expected", ROLES)
def test_regeneration_reservee_au_gerant(as_role, table, role, expected):
    assert as_role(role).post(f"{TABLES}{table.id}/regenerate-qr/").status_code == expected


# --- Zones ----------------------------------------------------------------------------------

def test_crud_zone(as_role):
    api = as_role("manager")
    zone = api.post(ZONES, {"name": "Terrasse", "position": 2}, format="json").json()
    assert zone == {"id": zone["id"], "name": "Terrasse", "position": 2}
    assert api.patch(f"{ZONES}{zone['id']}/", {"name": "Jardin"}, format="json").json()["name"] == "Jardin"
    assert api.get(ZONES).json() == [{**zone, "name": "Jardin"}]
    assert api.delete(f"{ZONES}{zone['id']}/").status_code == 204


def test_zone_avec_tables_non_supprimable(as_role, table):
    r = as_role("manager").delete(f"{ZONES}{table.zone_id}/")
    assert r.status_code == 400 and "tables" in r.json()["detail"]
    assert Zone.objects.filter(pk=table.zone_id).exists()


def test_nom_de_zone_unique(as_role, salle):
    assert as_role("manager").post(ZONES, {"name": "Salle"}, format="json").status_code == 400


# --- Tables ---------------------------------------------------------------------------------

def test_creation_table(as_role, salle, settings):
    settings.PUBLIC_SITE_URL = "https://delicesdorodis.ci"
    r = as_role("manager").post(TABLES, {"number": 9, "zone": salle.id, "seats": 6}, format="json")
    table = Table.objects.get(number=9)
    assert r.json() == {"id": table.id, "number": 9, "zone": salle.id, "zone_name": "Salle", "seats": 6,
                        "is_active": True, "qr_url": f"https://delicesdorodis.ci/t/{table.qr_token}", "qr_version": 1}


def test_numero_de_table_unique(as_role, table):
    r = as_role("manager").post(TABLES, {"number": 5, "zone": table.zone_id}, format="json")
    assert r.status_code == 400 and r.json()["number"]


def test_liste_filtree_par_zone(as_role, table):
    terrasse = Zone.objects.create(name="Terrasse")
    Table.objects.create(number=12, zone=terrasse)
    api = as_role("manager")
    assert [t["number"] for t in api.get(TABLES).json()] == [5, 12]
    assert [t["number"] for t in api.get(TABLES, {"zone": terrasse.id}).json()] == [12]


def test_qr_version_et_jeton_non_modifiables(as_role, table):
    token = table.qr_token
    r = as_role("manager").patch(f"{TABLES}{table.id}/", {"qr_version": 9, "qr_url": "x", "seats": 2}, format="json")
    table.refresh_from_db()
    assert r.status_code == 200 and (table.qr_version, table.qr_token, table.seats) == (1, token, 2)


def test_regenerer_le_qr(as_role, table):
    old = Table.objects.get(pk=table.pk).qr_url
    r = as_role("manager").post(f"{TABLES}{table.id}/regenerate-qr/")
    assert r.status_code == 200
    assert r.json()["qr_version"] == 2 and r.json()["qr_url"] != old


# --- Fichiers --------------------------------------------------------------------------------

def test_qr_png(as_role, table):
    r = as_role("manager").get(f"{TABLES}{table.id}/qr.png")
    assert r["Content-Type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")
    assert 'filename="table-5-qr.png"' in r["Content-Disposition"]


def test_qr_png_table_inconnue(as_role):
    assert as_role("manager").get(f"{TABLES}999/qr.png").status_code == 404


def test_planche_une_page_par_table_active(as_role, table):
    Table.objects.create(number=6, zone=table.zone)
    Table.objects.create(number=7, zone=table.zone, is_active=False)
    r = as_role("manager").get(SHEET)
    assert r["Content-Type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert pages(r.content) == 2


def test_planche_filtree_par_zone(as_role, table):
    terrasse = Zone.objects.create(name="Terrasse")
    Table.objects.create(number=12, zone=terrasse)
    assert pages(as_role("manager").get(SHEET, {"zone": terrasse.id}).content) == 1


def test_planche_sans_table_active(as_role, table):
    Table.objects.update(is_active=False)
    r = as_role("manager").get(SHEET)
    assert r.status_code == 404 and r.json()["detail"]


def test_chevalet_d_une_seule_table(as_role, table):
    Table.objects.create(number=6, zone=table.zone)
    assert pages(as_role("manager").get(SHEET, {"number": 5}).content) == 1
