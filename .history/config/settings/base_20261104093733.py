from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

# Secret partagé avec le serveur Next.js (X-Frontend-Key) ; vide = X-Client-IP ignoré
FRONTEND_API_KEY = env("FRONTEND_API_KEY", default="")

# Revalidation du cache Next.js (route du site qui appelle revalidateTag) ; URL vide = désactivé
FRONTEND_REVALIDATE_URL = env("FRONTEND_REVALIDATE_URL", default="")
REVALIDATE_SECRET = env("REVALIDATE_SECRET", default="")

# Adresse du site Next.js : sert aux QR des tables (/t/<jeton>)
PUBLIC_SITE_URL = env("PUBLIC_SITE_URL", default="http://localhost:3000").rstrip("/")

# Admin déplacé hors de /admin/ (ex. "gestion-orodis/")
ADMIN_URL = env("ADMIN_URL", default="admin/")

INSTALLED_APPS = [
    "daphne",  # en premier : runserver passe en ASGI, prêt pour Channels (phase 3)
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Tiers
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "corsheaders",
    "django_filters",
    "axes",
    # Projet
    "apps.core",
    "apps.accounts",
    "apps.menu",
    "apps.tables",
    "apps.reservations",
    "apps.catering",
    "apps.orders",
    "apps.payments",
]

# Fournisseur de paiement (apps/payments/providers.py) : « manual » tant qu'aucun agrégateur n'est choisi
PAYMENT_PROVIDER = env("PAYMENT_PROVIDER", default="manual")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",  # toujours en dernier
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL")}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CACHES = {
#     "default": {
#         "BACKEND": "django_redis.cache.RedisCache",
#         "LOCATION": env("REDIS_URL", default="redis://localhost:6379/0"),
#     }
# }


CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "orodis-cache",
    }
}
# Temps réel (Django Channels) : même Redis que le cache ; préfixe propre à Channels, pas de collision
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [env("REDIS_URL", default="redis://localhost:6379/0")]},
    }
}

# Domaines autorisés à ouvrir un WebSocket : les pages du site Next.js
WS_ALLOWED_ORIGINS = env.list("WS_ALLOWED_ORIGINS", default=CORS_ALLOWED_ORIGINS)

# Authentification
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# django-axes : verrouillage après 5 échecs de connexion
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(hours=1)
AXES_RESET_ON_SUCCESS = True

# Langue et fuseau
LANGUAGE_CODE = "fr"
TIME_ZONE = "Africa/Abidjan"
USE_I18N = True
USE_TZ = True

# Fichiers
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    # Fermé par défaut : chaque vue publique déclare AllowAny explicitement
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "apps.core.throttling.AnonRateThrottle",
        "apps.core.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "reservations": "5/hour",
        "quotes": "5/hour",
        # Connexion du personnel, en plus du verrouillage django-axes après 5 échecs
        "login": "10/min",
        # Téléphone d'une table (routes /table/), compté par session : écritures (commandes, appels)
        "table": "30/min",
        # … et lectures (session, suivi, reçus), partagées par tous les téléphones de la table
        "table_read": "120/min",
        # Les limites des POST publics (réservations, devis) seront ajoutées avec leurs apps
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "API Les Délices d'Orodis",
    "DESCRIPTION": "Carte, réservations, devis traiteur, tables et connexion du personnel.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "ENUM_NAME_OVERRIDES": {
        "ReservationStatusEnum": "apps.reservations.models.Reservation.Status",
        "QuoteStatusEnum": "apps.catering.models.QuoteRequest.Status",
        "OrderStatusEnum": "apps.orders.models.Order.Status",
        "TableSessionStatusEnum": "apps.orders.models.TableSession.Status",
        "ServiceRequestStatusEnum": "apps.orders.models.ServiceRequest.Status",
        "PaymentMethodEnum": "apps.orders.models.Order.PaymentMethod",
    },
}

# E-mail (Brevo ou Gmail)
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="smtp-relay.brevo.com")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = True
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Les Délices d'Orodis <no-reply@delicesdorodis.ci>")
RESTAURANT_NOTIFY_EMAIL = env("RESTAURANT_NOTIFY_EMAIL", default="")
