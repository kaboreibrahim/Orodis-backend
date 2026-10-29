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
