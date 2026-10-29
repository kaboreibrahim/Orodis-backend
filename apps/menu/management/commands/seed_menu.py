from django.core.management.base import BaseCommand
from django.db import transaction

from apps.menu.models import Category, Dish, Option, OptionGroup, SubCategory

# (nom, min, max, [(option, supplément, par défaut)])
ACCOMPAGNEMENT = ("Accompagnement", 1, 1, [
    ("Attiéké", 0, True), ("Riz blanc", 0, False), ("Foutou banane", 500, False),
    ("Placali", 500, False), ("Alloco", 500, False),
])
PIMENT = ("Piment", 0, 1, [("Doux", 0, False), ("Moyen", 0, False), ("Fort", 0, False)])

MENU = [
    {"name": "Plats ivoiriens", "icon": "🍲", "subcategories": [
        {"name": "Sauces", "dishes": [
            {"name": "Kedjenou de poulet", "price": 4500, "featured": True, "prep": 25,
             "description": "Poulet mijoté à l'étouffée avec tomates, oignons et piment.",
             "options": [ACCOMPAGNEMENT, PIMENT]},
            {"name": "Sauce graine", "price": 4000, "prep": 20,
             "description": "Sauce aux noix de palme, viande ou poisson fumé.",
             "options": [ACCOMPAGNEMENT, PIMENT]},
            {"name": "Sauce arachide", "price": 4000, "prep": 20,
             "description": "Sauce onctueuse à la pâte d'arachide.",
             "options": [ACCOMPAGNEMENT, PIMENT]},
        ]},
        {"name": "Grillades", "dishes": [
            {"name": "Poulet braisé", "price": 5000, "featured": True, "prep": 30,
             "description": "Demi-poulet mariné et braisé au feu de bois.",
             "options": [ACCOMPAGNEMENT, PIMENT]},
            {"name": "Poisson braisé", "price": 6000, "prep": 30,
             "description": "Carpe entière braisée, oignons et tomates.",
             "options": [ACCOMPAGNEMENT, PIMENT]},
        ]},
        {"name": "Spécialités", "dishes": [
            {"name": "Garba spécial", "price": 3500, "featured": True, "prep": 10,
             "description": "Attiéké, thon frit, oignons, tomates et piment.",
             "options": [PIMENT]},
            {"name": "Alloco poisson", "price": 3000, "prep": 15,
             "description": "Bananes plantains frites et poisson frit.",
             "options": [PIMENT]},
        ]},
    ]},
    {"name": "Boissons", "icon": "🥤", "subcategories": [
        {"name": "Jus naturels", "dishes": [
            {"name": "Bissap", "price": 1000, "prep": 2, "description": "Jus de fleurs d'hibiscus, servi frais."},
            {"name": "Gnamakoudji", "price": 1000, "prep": 2, "description": "Jus de gingembre frais."},
            {"name": "Jus de baobab", "price": 1000, "prep": 2, "description": "Jus de pain de singe."},
        ]},
        {"name": "Sodas et eaux", "dishes": [
            {"name": "Eau minérale 50 cl", "price": 500, "prep": 1},
            {"name": "Coca-Cola 33 cl", "price": 800, "prep": 1},
        ]},
    ]},
    {"name": "Desserts", "icon": "🍨", "subcategories": [
        {"name": "Douceurs", "dishes": [
            {"name": "Dêguê", "price": 1000, "prep": 2, "description": "Mil au lait caillé sucré."},
            {"name": "Salade de fruits", "price": 1500, "prep": 5, "description": "Fruits frais de saison."},
        ]},
    ]},
]


class Command(BaseCommand):
    help = "Charge la carte de démonstration. Relançable sans créer de doublons."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Supprime toute la carte avant de la recharger.")

    @transaction.atomic
    def handle(self, *args, reset=False, **options):
        if reset:
            Dish.objects.all().delete()  # supprime aussi groupes et options
            SubCategory.objects.all().delete()
            Category.objects.all().delete()
            self.stdout.write(self.style.WARNING("Carte existante supprimée."))

        for c_pos, cat_data in enumerate(MENU):
            category, _ = Category.objects.update_or_create(
                name=cat_data["name"], defaults={"icon": cat_data["icon"], "position": c_pos, "is_active": True}
            )
            for s_pos, sub_data in enumerate(cat_data["subcategories"]):
                sub, _ = SubCategory.objects.update_or_create(
                    name=sub_data["name"], category=category, defaults={"position": s_pos, "is_active": True}
                )
                for d_pos, d in enumerate(sub_data["dishes"]):
                    dish, _ = Dish.objects.update_or_create(
                        name=d["name"], subcategory=sub,
                        defaults={
                            "price": d["price"],
                            "description": d.get("description", ""),
                            "is_featured": d.get("featured", False),
                            "is_available": True,
                            "prep_minutes": d["prep"],
                            "position": d_pos,
                        },
                    )
                    dish.option_groups.all().delete()  # recréés à l'identique à chaque lancement
                    for g_pos, (g_name, g_min, g_max, opts) in enumerate(d.get("options", [])):
                        group = OptionGroup.objects.create(
                            dish=dish, name=g_name, min_choices=g_min, max_choices=g_max, position=g_pos
                        )
                        Option.objects.bulk_create([
                            Option(group=group, name=o_name, price_delta=delta, is_default=default, position=o_pos)
                            for o_pos, (o_name, delta, default) in enumerate(opts)
                        ])

        self.stdout.write(self.style.SUCCESS(
            f"Carte chargée : {Category.objects.count()} catégories, {SubCategory.objects.count()} sous-catégories, "
            f"{Dish.objects.count()} plats, {Option.objects.count()} options."
        ))
