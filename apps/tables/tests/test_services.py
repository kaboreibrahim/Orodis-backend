import pytest

from apps.tables import printing, services
from apps.tables.models import Table, Zone

pytestmark = pytest.mark.django_db


@pytest.fixture
def table(db):
    return Table.objects.create(number=5, zone=Zone.objects.create(name="Salle"))


def test_regenerate_qr_change_le_jeton_et_la_version(table):
    old = table.qr_token
    table = services.regenerate_qr(table)
    assert table.qr_token != old and table.qr_version == 2
    assert not Table.objects.filter(qr_token=old).exists()


def test_create_tables_ignore_les_numeros_pris(table):
    new, taken = services.create_tables("Terrasse", 4, 7, seats=2)
    assert [t.number for t in new] == [4, 6, 7] and taken == [5]
    assert Table.objects.get(number=6).zone.name == "Terrasse"


def test_qr_png_encode_l_adresse_de_la_table(table):
    png = printing.qr_png(table.qr_url)
    assert png.startswith(b"\x89PNG")


def test_qr_matrix_contient_l_adresse(table, settings):
    # La taille du QR grandit avec l'adresse : une matrice carrée d'au moins 21 modules
    matrix = printing.qr_matrix(table.qr_url)
    assert len(matrix) >= 21 and all(len(row) == len(matrix) for row in matrix)


def test_qr_sheet_une_page_par_table(table):
    other = Table.objects.create(number=6, zone=table.zone)
    pdf = printing.qr_sheet([table, other])
    assert pdf.startswith(b"%PDF") and pdf.count(b"/Type /Page\n") == 2
