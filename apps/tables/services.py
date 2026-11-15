import uuid

from django.db import transaction

from .models import Table, Zone


@transaction.atomic
def regenerate_qr(table):
    """Nouveau jeton + version suivante : l'ancien chevalet ne fonctionne plus."""
    table = Table.objects.select_for_update().get(pk=table.pk)
    table.qr_token = uuid.uuid4()
    table.qr_version += 1
    table.save(update_fields=["qr_token", "qr_version", "updated_at"])
    return table


@transaction.atomic
def create_tables(zone_name, first, last, seats=4):
    """Crée les tables first..last dans la zone (créée si besoin). Les numéros déjà pris sont ignorés."""
    zone, _ = Zone.objects.get_or_create(name=zone_name)
    taken = set(Table.objects.filter(number__range=(first, last)).values_list("number", flat=True))
    new = [Table(number=n, zone=zone, seats=seats) for n in range(first, last + 1) if n not in taken]
    Table.objects.bulk_create(new)
    return new, sorted(taken)


class NumbersTaken(Exception):
    """Certains numéros du lot existent déjà : rien n'est créé."""

    def __init__(self, numbers):
        self.numbers = numbers
        super().__init__(numbers)


@transaction.atomic
def create_range(zone, first, count, seats=4, is_active=True):
    """Crée `count` tables numérotées à partir de `first`, chacune avec son QR. Tout ou rien :
    si un numéro est déjà pris, lève NumbersTaken et ne crée aucune table."""
    numbers = range(first, first + count)
    taken = sorted(Table.objects.filter(number__in=numbers).values_list("number", flat=True))
    if taken:
        raise NumbersTaken(taken)
    return Table.objects.bulk_create([Table(number=n, zone=zone, seats=seats, is_active=is_active) for n in numbers])
