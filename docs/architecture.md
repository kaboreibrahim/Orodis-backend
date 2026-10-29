# Architecture backend Django — Les Délices d'Orodis

29 oct. 2026 · @ibrahim

## Vue d'ensemble

Un seul projet Django sert d'API à toutes les interfaces : le site vitrine Next.js, l'app de commande par QR, l'écran cuisine et le tableau de bord du gérant. La phase 2 (5 – 11 nov) livre le socle, la carte, les réservations et les demandes de devis. Les apps commandes, temps réel et paiement sont prévues dès maintenant dans l'arborescence, mais codées en phases 3 et 4.

Les interfaces ne parlent qu'à l'API ; seule l'API touche la base, Redis et les fichiers.

| Couche | Choix | Rôle |
| --- | --- | --- |
| Langage | Python 3.12, Django 5.1 | Modèles, admin, logique métier |
| API | Django REST Framework 3.15 + drf-spectacular | Endpoints JSON, documentation Swagger sur /api/docs/ |
| Base de données | PostgreSQL 16 | Données de production |
| Cache et file | Redis 7 | Cache de la carte (phase 2), canal temps réel Django Channels (phase 3) |
| Serveur | Daphne (ASGI) | Sert HTTP et, plus tard, WebSocket avec le même processus |
| Fichiers | WhiteNoise (statiques), volume Docker /media (photos des plats) | Pas de service S3 nécessaire au départ |
| Authentification | JWT (djangorestframework-simplejwt) | Connexion du gérant et du personnel depuis Next.js |
| Hébergement | Contabo Cloud VPS 4 + Coolify | Un service Django, un Next.js, un PostgreSQL, un Redis |

Le site public n'a jamais de compte client : il lit la carte et envoie des réservations ou des devis sans connexion. Seul le personnel se connecte.

## Arborescence et apps

Le projet se découpe en 8 apps, dont 6 codées en phase 2. Chaque app garde ses modèles, serializers, vues et tests ; la logique métier va dans `services.py`, jamais dans les vues.

Le dépôt `Orodis_backend` est lui-même ce dossier `backend/` : `manage.py` et `config/` sont à sa racine.

```
backend/                     # = racine du dépôt Orodis_backend
├── config/
│   ├── settings/
│   │   ├── base.py          # commun
│   │   ├── dev.py           # DEBUG, SQLite ou Postgres local
│   │   └── prod.py          # sécurité, WhiteNoise, logs
│   ├── urls.py              # /admin/, /api/v1/, /api/docs/
│   ├── asgi.py              # Daphne (+ Channels en phase 3)
│   └── wsgi.py
├── apps/
│   ├── core/                # modèle de base horodaté, réglages du restaurant, permissions, utilitaires
│   ├── accounts/            # utilisateur personnalisé + rôles
│   ├── menu/                # catégories, sous-catégories, plats, options
│   ├── tables/              # zones, tables, jeton QR
│   ├── reservations/        # créneaux, réservations
│   ├── catering/            # demandes de devis traiteur
│   ├── orders/              # phase 3 : commandes, lignes, statuts
│   └── payments/            # phase 4 : Wave, Orange Money, MTN MoMo, espèces
├── templates/admin/         # surcharge légère de l'admin (logo, couleurs)
├── requirements/
│   ├── base.txt
│   ├── dev.txt              # pytest, factory-boy, ruff
│   └── prod.txt
├── Dockerfile
├── entrypoint.sh            # migrate, collectstatic, daphne
├── manage.py
└── .env.example
```

Contenu type d'une app :

```
apps/menu/
├── models.py
├── admin.py
├── serializers.py
├── views.py         # ViewSets DRF
├── urls.py          # router DRF
├── services.py      # règles métier
├── selectors.py     # requêtes de lecture optimisées (select_related, prefetch_related)
└── tests/
```

## Modèles de données (phase 2)

Tous les modèles héritent de `core.TimeStampedModel` (`created_at`, `updated_at`). Les prix sont des entiers en francs CFA (`PositiveIntegerField`), jamais des décimaux. Les choix de statut sont des `TextChoices`.

### core

**RestaurantSettings** — une seule ligne (singleton), modifiable dans l'admin.

| Champ | Type | Note |
| --- | --- | --- |
| name | CharField | Les Délices d'Orodis |
| phone, whatsapp, email | CharField / EmailField | Repris sur le site et les reçus |
| address, maps_url | TextField / URLField | Page Nous trouver |
| opening_hours | JSONField | `{"lun": [["11:00","23:00"]], ...}` |
| reservation_slot_minutes | PositiveSmallIntegerField | 30 par défaut |
| reservation_max_party | PositiveSmallIntegerField | Au-delà : renvoi vers le traiteur |
| reservation_covers_per_slot | PositiveSmallIntegerField | Couverts max par créneau ; créneau « complet » au-delà |
| rccm, ncc, vat_rate | CharField / DecimalField | Pour les reçus (phase 3), vides tant que non fournis |

### menu

| Modèle | Champs principaux | Relations |
| --- | --- | --- |
| Category | name, slug, icon, position, is_active | — |
| SubCategory | name, slug, photo (facultative), position, is_active | category → Category |
| Dish | name, slug, description, price, photo (facultative), is_available, is_featured, position, prep_minutes | subcategory → SubCategory |
| OptionGroup | name (ex. « Accompagnement »), min_choices, max_choices, position | dish → Dish |
| Option | name (ex. « Foutou »), price_delta (ex. 500), is_default, is_available | group → OptionGroup |

- `is_available` sert au gérant pour masquer un plat en rupture sans le supprimer.
- Les photos passent par une fonction `upload_to` (`menu/dishes/<slug>.<ext>`) et sont redimensionnées à 1200 px à l'enregistrement (Pillow), pour rester légères sur mobile.
- Une option « Piment » est un `OptionGroup` (min 0, max 1) avec les options Doux, Moyen, Fort à 0 F.

### tables

| Modèle | Champs principaux | Note |
| --- | --- | --- |
| Zone | name (Salle, Terrasse), position | — |
| Table | number (unique), zone → Zone, seats, is_active, qr_token (UUID), qr_version | Le QR pointe vers `/t/<qr_token>` |

- Régénérer le QR = nouveau `qr_token` + `qr_version + 1` : l'ancien chevalet ne fonctionne plus.
- Le statut « libre / occupée » n'est pas stocké : il sera calculé en phase 3 à partir des commandes ouvertes.

### reservations

**Reservation**

| Champ | Type | Note |
| --- | --- | --- |
| reference | CharField unique | Ex. `R-2611-0042`, généré par le service |
| date, time | DateField, TimeField | Le créneau choisi |
| party_size | PositiveSmallIntegerField | 1 à `reservation_max_party` |
| name, phone | CharField | Téléphone normalisé au format +225 |
| note | TextField facultatif | Anniversaire, chaise bébé… |
| status | TextChoices | pending, confirmed, refused, cancelled, no_show, completed |
| table | FK Table, null | Attribuée à l'acceptation |
| source | TextChoices | site, phone, walk_in |
| handled_by, handled_at | FK User, DateTimeField | Qui a accepté ou refusé |
| refusal_reason | CharField facultatif | Repris dans le message au client |

Index sur `(date, status)` pour la liste du jour.

### catering

**QuoteRequest**

| Champ | Type | Note |
| --- | --- | --- |
| reference | CharField unique | Ex. `D-2611-0007` |
| event_type | TextChoices | mariage, anniversaire, bapteme, cocktail, seminaire, buffet, soiree_dinatoire, diner_gala |
| event_date | DateField | — |
| guests | PositiveIntegerField | Minimum à confirmer avec le client |
| place_type, place_detail | TextChoices / CharField | restaurant, domicile, autre + commune ou salle |
| formula | TextChoices | cocktail, buffet, diner_servi, indecis |
| name, whatsapp, email | CharField / EmailField facultatif | — |
| message | TextField facultatif | Envies, budget, matériel |
| status | TextChoices | new, contacted, quote_sent, won, lost |
| internal_note | TextField | Visible du gérant seulement |

## API REST

Toutes les routes sont préfixées par `/api/v1/`. Les routes publiques ne demandent aucune connexion ; les routes `/manage/` exigent un JWT de membre du personnel. Le Swagger est servi sur `/api/docs/`.

### Routes publiques (site vitrine, app QR)

| Méthode | Route | Rôle |
| --- | --- | --- |
| GET | /settings/ | Coordonnées, horaires, liens (pied de page, Nous trouver) |
| GET | /menu/ | Carte complète imbriquée : catégories → sous-catégories → plats → options, plats disponibles seulement |
| GET | /menu/dishes/{slug}/ | Fiche d'un plat avec ses options |
| GET | /menu/featured/ | Plats mis en avant sur l'accueil |
| GET | /reservations/availability/?date=2026-11-28&party=4 | Créneaux du jour avec `available: true/false` |
| POST | /reservations/ | Crée une réservation en statut pending, renvoie sa référence |
| POST | /catering/quotes/ | Crée une demande de devis, renvoie sa référence et le lien WhatsApp pré-rempli |
| GET | /tables/resolve/{qr_token}/ | Phase 3 : renvoie le numéro de table d'un QR, 404 si inactif ou régénéré |

`/menu/` est mis en cache Redis 10 minutes ; le cache est vidé par un signal `post_save` / `post_delete` sur les modèles de la carte, pour qu'une modification du gérant apparaisse tout de suite.

### Routes du personnel

| Méthode | Route | Rôle |
| --- | --- | --- |
| POST | /auth/token/ , /auth/token/refresh/ | Connexion JWT |
| GET | /auth/me/ | Utilisateur connecté et son rôle |
| CRUD | /manage/categories/, /manage/subcategories/, /manage/dishes/, /manage/option-groups/ | Gestion de la carte (en plus de l'admin Django) |
| PATCH | /manage/dishes/{id}/availability/ | Rupture de stock en un clic |
| CRUD | /manage/zones/, /manage/tables/ | Tables et zones |
| POST | /manage/tables/{id}/regenerate-qr/ | Nouveau jeton, version + 1 |
| GET | /manage/tables/{id}/qr.png et /manage/tables/qr-sheet.pdf | QR seul ou planche de chevalets A5 à imprimer |
| GET | /manage/reservations/?date=&status= | Liste filtrée (jour, en attente…) |
| POST | /manage/reservations/{id}/confirm/ | Corps : `table_id` facultatif ; renvoie le lien WhatsApp de confirmation |
| POST | /manage/reservations/{id}/refuse/ | Corps : `reason` ; renvoie le lien WhatsApp de refus |
| POST | /manage/reservations/{id}/cancel/ , /no-show/ , /complete/ | Suite du cycle de vie |
| POST | /manage/reservations/ | Saisie d'une réservation prise au téléphone |
| GET, PATCH | /manage/quotes/ , /manage/quotes/{id}/ | Suivi des devis (statut, note interne) |
| GET, PATCH | /manage/settings/ | Réglages du restaurant (gérant seulement) |

Les actions de statut sont des `@action` DRF qui appellent `services.py` : la vue ne change jamais un statut elle-même.

### Conventions

- Pagination `PageNumberPagination`, 20 par page, sauf `/menu/` (non paginé).
- Erreurs au format DRF standard (`{"champ": ["message"]}`), messages en français (`LANGUAGE_CODE = "fr"`).
- Dates en ISO 8601, fuseau `Africa/Abidjan` (UTC+0).
- Les images sont renvoyées en URL absolue (`request.build_absolute_uri`).

## Réservation : règles métier

Une réservation faite sur le site arrive toujours en attente ; c'est le gérant qui la confirme, et le client reçoit la réponse par WhatsApp. Toute la logique vit dans `apps/reservations/services.py`.

### Calcul des créneaux disponibles

1. Lire `opening_hours` pour le jour demandé ; aucun horaire = jour fermé, liste vide.
2. Découper chaque plage en créneaux de `reservation_slot_minutes`, en s'arrêtant 60 min avant la fermeture.
3. Pour chaque créneau, additionner `party_size` des réservations `pending` + `confirmed` à cette heure.
4. Marquer le créneau `available: false` si total + couverts demandés dépasse `reservation_covers_per_slot`, ou si le créneau est déjà passé aujourd'hui.

### Validation à la création (POST public)

- Date entre aujourd'hui et J+60 ; créneau disponible au moment de l'enregistrement (revérifié dans une transaction avec `select_for_update` sur les réservations du créneau).
- `party_size` au-delà de `reservation_max_party` → erreur avec un message qui renvoie vers la page Traiteur.
- Numéro ivoirien à 10 chiffres, enregistré en `+225XXXXXXXXXX`.
- Anti-abus : `throttle` DRF de 5 réservations par heure et par IP, plus un champ piège caché (honeypot) dans le formulaire Next.js.

### Cycle de vie

| De | Vers | Qui | Effet |
| --- | --- | --- | --- |
| — | pending | Client (site) | Référence créée, apparaît chez le gérant |
| pending | confirmed | Gérant | Table attribuée (facultatif), lien WhatsApp de confirmation |
| pending | refused | Gérant | Motif obligatoire, lien WhatsApp de refus |
| confirmed | cancelled | Gérant | Le créneau se libère |
| confirmed | completed / no_show | Gérant | Fin de service, sert aux statistiques |

Une réservation saisie par le gérant (téléphone, sur place) est créée directement en `confirmed`. Toute autre transition lève une `ValidationError`.

### Confirmation par WhatsApp

Le backend ne fait aucun envoi : il construit un lien `https://wa.me/225XXXXXXXXXX?text=...` (texte encodé avec `urllib.parse.quote`) que le tableau de bord ouvre au clic. C'est gratuit et sans compte à ouvrir. Modèle de message de confirmation :

```
Bonjour {name}, votre réservation aux Délices d'Orodis est confirmée :
{date} à {time}, {party_size} personnes (réf. {reference}).
À très vite !
```

Pour un envoi SMS automatique plus tard, `services.py` appelle une fonction `notify(reservation, event)` qui, en phase 2, ne fait que renvoyer le lien. Il suffira d'y brancher un fournisseur SMS sans toucher aux vues. [Canal définitif à choisir avec le client.]

Le même principe sert aux devis : `POST /catering/quotes/` renvoie un lien `wa.me` vers le numéro WhatsApp du restaurant, pré-rempli avec le récapitulatif de la demande, et un e-mail est envoyé au restaurant (`send_mail`, SMTP Gmail ou Brevo).

## Authentification, rôles et sécurité

Un modèle `accounts.User` personnalisé est créé dès la première migration (`AUTH_USER_MODEL`), avec un champ `role` ; c'est impossible à ajouter proprement plus tard.

| Rôle | Accès phase 2 | Accès prévu ensuite |
| --- | --- | --- |
| manager (gérant) | Tout : carte, tables, réservations, devis, réglages, admin Django | Statistiques, paiements, personnel |
| cashier (caisse) | Réservations, consultation de la carte, ruptures de stock | Commandes, encaissement, reçus |
| waiter (serveur) | Réservations du jour en lecture | Commandes de ses tables, appels serveur |
| kitchen (cuisine) | — | Écran cuisine seulement |

Permissions DRF dans `core/permissions.py` : `IsStaffRole`, `IsManager`, et `HasRole("cashier", "manager")` paramétrable, appliquées par ViewSet.

### Réglages de sécurité (prod.py)

- `DEBUG = False`, `SECRET_KEY` et mots de passe uniquement dans les variables d'environnement Coolify.
- `ALLOWED_HOSTS` et `CSRF_TRUSTED_ORIGINS` limités aux domaines du restaurant ; `CORS_ALLOWED_ORIGINS` = le seul domaine Next.js (django-cors-headers).
- `SECURE_PROXY_SSL_HEADER` (Coolify termine le HTTPS), `SECURE_SSL_REDIRECT`, cookies `Secure`, HSTS.
- JWT : accès 30 min, rafraîchissement 7 jours avec rotation et liste noire (`rest_framework_simplejwt.token_blacklist`).
- Admin Django déplacé hors de `/admin/` (ex. `/gestion-orodis/`) et protégé par django-axes (verrouillage après 5 échecs).
- Throttling DRF : `anon` 60/min, plus les limites dédiées aux POST publics (réservations, devis).
- Fichiers envoyés : images seulement, 5 Mo maximum, vérifiées par Pillow.
- Le numéro de téléphone et le nom du client ne sont jamais renvoyés par une route publique.

## Configuration, Docker et déploiement

Le backend tourne dans une image Docker unique, déployée par Coolify depuis le dépôt GitHub ; PostgreSQL et Redis sont des services Coolify à part. Le détail du serveur est dans le guide de déploiement déjà rédigé.

### Variables d'environnement (.env.example)

```
DJANGO_SETTINGS_MODULE=config.settings.prod
SECRET_KEY=
ALLOWED_HOSTS=api.delicesdorodis.ci
CSRF_TRUSTED_ORIGINS=https://api.delicesdorodis.ci
CORS_ALLOWED_ORIGINS=https://delicesdorodis.ci
DATABASE_URL=postgres://orodis:motdepasse@postgres:5432/orodis
REDIS_URL=redis://redis:6379/0
EMAIL_HOST=smtp-relay.brevo.com
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
RESTAURANT_NOTIFY_EMAIL=orodistraiteur@gmail.com
ADMIN_URL=gestion-orodis/
SENTRY_DSN=
```

Les noms de domaine sont des exemples : [domaine à confirmer avec le client].

### Dépendances (requirements/base.txt)

```
Django~=5.1
djangorestframework~=3.15
djangorestframework-simplejwt~=5.3
drf-spectacular~=0.27
django-cors-headers~=4.4
django-environ~=0.11
django-filter~=24.3
django-redis~=5.4
django-axes~=6.5
psycopg[binary]~=3.2
Pillow~=11.0
qrcode[pil]~=8.0
reportlab~=4.2
daphne~=4.1
whitenoise~=6.7
sentry-sdk~=2.17
```

Phase 3 ajoutera `channels` et `channels-redis`.

### Dockerfile

```
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libjpeg62-turbo zlib1g && rm -rf /var/lib/apt/lists/*
COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/prod.txt
COPY . .
RUN useradd -m app && chown -R app /app
USER app
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
```

### entrypoint.sh

```
#!/bin/sh
set -e
python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

### Dans Coolify

- Application « orodis-api » : build Dockerfile, dossier racine du dépôt (`/`), port 8000, domaine `api.…`, volume persistant monté sur `/app/media`.
- Health check sur `GET /api/v1/health/` (renvoie 200 si la base et Redis répondent).
- Sauvegarde quotidienne de PostgreSQL activée dans Coolify, vers un stockage S3.
- En local : un `docker-compose.dev.yml` avec postgres, redis et le backend en `runserver`.

### Commandes de gestion utiles

- `python manage.py seed_menu` : charge la carte de démonstration des maquettes (Kedjenou 4 500 F, Garba spécial 3 500 F…) pour développer avant d'avoir la vraie carte.
- `python manage.py create_tables --zone Salle --from 1 --to 8` : crée les tables et leurs jetons QR.

## Ordre de développement et suite

En 7 jours, cet ordre fait arriver la première réservation du site chez le gérant le dimanche 8 nov, et sa confirmation WhatsApp le lundi 9. La carte est servie à Next.js dès le samedi 7.

| Jour | Livrable backend | Fini quand |
| --- | --- | --- |
| Jeu 5 nov | Projet, settings dev/prod, `accounts.User`, `core`, Docker, dépôt GitHub | `docker compose up` démarre, admin accessible |
| Ven 6 nov | App `menu` : modèles, admin avec ordre et photos, `seed_menu` | La carte de démo est saisissable et visible dans l'admin |
| Sam 7 nov | API carte publique + cache, Swagger, déploiement Coolify sur le domaine de test | Next.js lit `/api/v1/menu/` en HTTPS |
| Dim 8 nov | Apps `tables` et `reservations` : modèles, service de disponibilité, POST public | Une réservation du site arrive en pending |
| Lun 9 nov | Routes `/manage/` réservations, JWT, rôles, liens WhatsApp | Le gérant confirme et le client reçoit le message |
| Mar 10 nov | App `catering`, e-mail au restaurant, QR PNG et planche PDF | Un devis arrive par e-mail ; les chevalets s'impriment |
| Mer 11 nov | Tests pytest des services, sécurité prod, sauvegarde | Tests verts, point de validation avec le client |

### Ce que la phase 2 prépare pour la suite

- **Phase 3 (commandes QR, temps réel)** : app `orders` avec `Order` (table, statut, total) et `OrderItem` (plat, options choisies, prix figé au moment de la commande). Django Channels sur le même Daphne : un groupe WebSocket `kitchen` et un groupe `table_<id>`, alimentés par `services.py` après chaque changement de statut.
- **Phase 3 (reçus)** : numérotation `R-000208` par séquence PostgreSQL, PDF A4 et ticket 80 mm générés par ReportLab à partir des `RestaurantSettings` (RCCM, NCC, TVA).
- **Phase 4 (paiement)** : app `payments` derrière une interface `PaymentProvider` (initier, vérifier, webhook), pour brancher l'agrégateur choisi (Wave, Orange Money, MTN MoMo) sans toucher aux commandes. [Agrégateur à choisir avec le client.]

### Questions ouvertes pour le client

- Horaires d'ouverture, durée d'un créneau et nombre de couverts par créneau.
- Taille maximale d'un groupe en réservation avant de passer au traiteur.
- Nombre minimum d'invités pour un devis traiteur.
- Nom de domaine et adresse e-mail qui reçoit les réservations et les devis.
- Confirmation par WhatsApp seulement, ou SMS aussi.
