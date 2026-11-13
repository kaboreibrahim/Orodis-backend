"""Point d'entrée de Passenger (LWS cPanel, « Setup Python App ») : il cherche « application » dans ce fichier."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

from config.wsgi import application  # noqa: F401
