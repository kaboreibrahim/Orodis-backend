# Orodis backend — Les Délices d'Orodis

API Django/DRF unique pour le site Next.js, l'app QR, l'écran cuisine et le tableau de bord du gérant.
L'architecture complète (modèles, routes, règles métier, déploiement) est dans [docs/architecture.md](docs/architecture.md) : la lire avant toute nouvelle app.

## Règles

- Prix en entiers FCFA (`PositiveIntegerField`), jamais de `Decimal` ni de `float`.
- Logique métier dans `services.py`, lectures optimisées dans `selectors.py` ; les vues ne changent jamais un statut elles-mêmes.
- Messages d'erreur et textes visibles en français (`LANGUAGE_CODE = "fr"`), fuseau `Africa/Abidjan`.
- Tous les modèles héritent de `core.TimeStampedModel` ; statuts en `TextChoices`.
- Un test pytest par fonction de service.
- Une app à la fois, dans l'ordre du tableau « Ordre de développement » ; valider les migrations avant de passer à la suivante.
- Le nom et le téléphone d'un client ne sortent jamais par une route publique.

## Stack

Python 3.12, Django 5.1, DRF 3.15, PostgreSQL 16, Redis 7, Daphne, JWT (simplejwt). Dépendances dans `requirements/` (base, dev, prod).
