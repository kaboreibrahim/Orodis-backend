from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catering.models import CateringFormula

# price_from laissé vide : les prix sont à saisir par le client dans l'admin
FORMULAS = [
    {
        "name": "Cocktail dînatoire",
        "description": "Bouchées salées et sucrées servies debout, idéal pour réceptions et inaugurations.",
        "items": [
            "Assortiment de bouchées salées", "Mini-brochettes et beignets",
            "Douceurs sucrées", "Jus naturels (bissap, gnamakoudji)", "Service en salle",
        ],
    },
    {
        "name": "Buffet",
        "highlighted": True,
        "description": "Un grand buffet ivoirien et international en libre-service.",
        "items": [
            "Entrées froides et salades", "Plats chauds au choix (kedjenou, poulet braisé, poisson braisé…)",
            "Accompagnements : attiéké, riz, alloco", "Desserts et fruits de saison",
            "Boissons non alcoolisées", "Mise en place et réchauds",
        ],
    },
    {
        "name": "Dîner servi",
        "description": "Repas assis servi à table, pour mariages et dîners de gala.",
        "items": [
            "Entrée, plat et dessert servis à l'assiette", "Menu composé avec le chef",
            "Personnel de service", "Vaisselle et nappage",
        ],
    },
]


class Command(BaseCommand):
    help = "Charge les 3 formules traiteur des maquettes. Relançable ; ne touche jamais aux prix saisis."

    @transaction.atomic
    def handle(self, *args, **options):
        for position, data in enumerate(FORMULAS):
            formula, created = CateringFormula.objects.get_or_create(
                name=data["name"],
                defaults={
                    "description": data["description"], "items": data["items"],
                    "is_highlighted": data.get("highlighted", False), "position": position,
                },
            )
            self.stdout.write(f"{'Créée' if created else 'Déjà présente'} : {formula.name}")
        self.stdout.write(self.style.SUCCESS(f"{CateringFormula.objects.count()} formule(s) en base."))
