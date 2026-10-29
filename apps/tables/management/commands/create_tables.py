from django.core.management.base import BaseCommand, CommandError

from apps.tables.services import create_tables


class Command(BaseCommand):
    help = "Crée des tables numérotées et leurs jetons QR. Ex. : create_tables --zone Salle --from 1 --to 8"

    def add_arguments(self, parser):
        parser.add_argument("--zone", required=True)
        parser.add_argument("--from", dest="first", type=int, required=True)
        parser.add_argument("--to", dest="last", type=int, required=True)
        parser.add_argument("--seats", type=int, default=4)

    def handle(self, *args, zone, first, last, seats, **options):
        if first < 1 or last < first:
            raise CommandError("Intervalle invalide : --from doit être ≥ 1 et ≤ --to.")
        new, skipped = create_tables(zone, first, last, seats)
        self.stdout.write(self.style.SUCCESS(f"{len(new)} table(s) créée(s) dans « {zone} »."))
        if skipped:
            self.stdout.write(self.style.WARNING(f"Numéros déjà pris, ignorés : {', '.join(map(str, skipped))}."))
