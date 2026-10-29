from .base import *  # noqa: F403

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]
CORS_ALLOWED_ORIGINS = ["http://localhost:3000"]  # Next.js en local
CSRF_TRUSTED_ORIGINS = ["http://localhost:3000"]

# Les e-mails s'affichent dans le terminal au lieu de partir
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Permet de naviguer dans l'API navigable de DRF une fois connecté à l'admin
REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] = [  # noqa: F405
    *REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"],  # noqa: F405
    "rest_framework.authentication.SessionAuthentication",
]
