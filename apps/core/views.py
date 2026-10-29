from django.core.cache import cache
from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import RestaurantSettings
from .serializers import PublicSettingsSerializer


class HealthCheckView(APIView):
    """Utilisé par Coolify : 200 si la base et Redis répondent, 503 sinon."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    @extend_schema(exclude=True)
    def get(self, request):
        checks = {"database": _check_database(), "redis": _check_redis()}
        healthy = all(value == "ok" for value in checks.values())
        return Response({"status": "ok" if healthy else "erreur", **checks}, status=200 if healthy else 503)


class PublicSettingsView(APIView):
    """Coordonnées et horaires pour le pied de page et la page Nous trouver."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []  # appelée par Next.js sur chaque page

    @extend_schema(responses=PublicSettingsSerializer, summary="Coordonnées et horaires du restaurant")
    def get(self, request):
        return Response(PublicSettingsSerializer(RestaurantSettings.load()).data)


def _check_database():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return "ok"
    except Exception:
        return "erreur"


def _check_redis():
    try:
        cache.set("health_check", "ok", 5)
        return "ok" if cache.get("health_check") == "ok" else "erreur"
    except Exception:
        return "erreur"
