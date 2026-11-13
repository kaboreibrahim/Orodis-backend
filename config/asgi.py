import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

# Non utilisé chez LWS (Passenger sert config.wsgi) ; gardé pour un éventuel serveur ASGI
application = get_asgi_application()
