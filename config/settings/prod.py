import sentry_sdk

from .base import *  # noqa: F403
from .base import env

DEBUG = False

# Passenger transmet lui-même le HTTPS à Django : pas de SECURE_PROXY_SSL_HEADER.
# Si « Forcer HTTPS » est déjà activé dans cPanel et que le site boucle en redirections, mettre false.
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# HSTS court au départ ; passer à 31536000 (1 an) une fois le domaine définitif validé
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False

# URL publique des photos, même si Next.js appelle l'API par son adresse interne
MEDIA_URL = env("PUBLIC_MEDIA_URL")

# WhiteNoise : statiques compressés et versionnés
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{asctime} {levelname} {name} : {message}", "style": "{"},
    },
    "handlers": {
        # Passenger écrit la sortie d'erreur dans stderr.log, à la racine de l'application
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}

SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=False,  # pas de nom ni de téléphone client envoyés à Sentry
        traces_sample_rate=0.1,
    )
