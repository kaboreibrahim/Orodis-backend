from django.core.management.base import BaseCommand

from apps.orders import services


class Command(BaseCommand):
    help = "Supprime les événements temps réel de plus de 24 h (cron cPanel, une fois par nuit)."

    def handle(self, *args, **options):
        count = services.purge_events()
        self.stdout.write(self.style.SUCCESS(f"{count} événement(s) supprimé(s)."))
