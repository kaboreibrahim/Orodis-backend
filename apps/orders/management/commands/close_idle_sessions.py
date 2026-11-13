from django.core.management.base import BaseCommand

from apps.orders import services


class Command(BaseCommand):
    help = "Ferme les sessions de table sans activité depuis 6 h (cron cPanel, toutes les heures)."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=services.IDLE_HOURS)

    def handle(self, *args, hours, **options):
        count = services.close_idle_sessions(hours=hours)
        self.stdout.write(self.style.SUCCESS(f"{count} session(s) fermée(s)."))
