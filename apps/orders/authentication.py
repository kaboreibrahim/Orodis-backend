from django.contrib.auth.models import AnonymousUser
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.throttling import SimpleRateThrottle

from apps.core.throttling import get_client_ip

from .models import TableSession


class TableSessionAuthentication(BaseAuthentication):
    """En-tête X-Session-Token → la session de table dans request.auth (request.user reste anonyme).
    Une session fermée reste lisible (suivi, reçu) ; les services refusent d'y ajouter quoi que ce soit."""

    def authenticate(self, request):
        token = request.META.get("HTTP_X_SESSION_TOKEN", "").strip()
        if not token:
            return None
        session = TableSession.objects.select_related("table__zone").filter(token=token).first()
        if session is None:
            raise AuthenticationFailed("Session inconnue. Scannez à nouveau le QR code de la table.")
        return AnonymousUser(), session

    def authenticate_header(self, request):
        return "X-Session-Token"  # 401 plutôt que 403 sans jeton


class HasTableSession(BasePermission):
    message = "Scannez le QR code de votre table pour commander."

    def has_permission(self, request, view):
        return isinstance(request.auth, TableSession)


class TableSessionThrottle(SimpleRateThrottle):
    """Throttles du téléphone, comptés par session (par IP du visiteur sans session) :
    - « table_read » (GET : session, suivi, reçus) : 120/min, car plusieurs téléphones d'une même table
      partagent la session et chaque reconnexion recharge l'état ;
    - « table » (POST : commandes, appels, ouverture de session) : 30/min.
    Les deux compteurs sont séparés : consulter le suivi n'empêche jamais de commander."""

    scope = "table"
    read_scope = "table_read"

    def allow_request(self, request, view):
        self.scope = self.read_scope if request.method in SAFE_METHODS else type(self).scope
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        ident = f"s{request.auth.pk}" if isinstance(request.auth, TableSession) else get_client_ip(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class TableEventsThrottle(TableSessionThrottle):
    """Polling : compteur à part, pour que plusieurs téléphones d'une table (un appel toutes les 4 s chacun)
    n'épuisent jamais « table_read »."""

    read_scope = "table_events"


class TableSessionScheme(OpenApiAuthenticationExtension):
    """Fait apparaître l'en-tête X-Session-Token dans le Swagger (/api/docs/)."""

    target_class = "apps.orders.authentication.TableSessionAuthentication"
    name = "TableSession"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "header", "name": "X-Session-Token"}
