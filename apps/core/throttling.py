import ipaddress
import secrets

from django.conf import settings
from rest_framework import throttling


def get_client_ip(request):
    """IP du visiteur. Next.js (côté serveur) la transmet dans X-Client-IP ; on ne la croit
    que si X-Frontend-Key correspond à FRONTEND_API_KEY. Sinon : REMOTE_ADDR."""
    meta = request.META
    expected = settings.FRONTEND_API_KEY
    provided = meta.get("HTTP_X_FRONTEND_KEY", "")
    client_ip = meta.get("HTTP_X_CLIENT_IP", "").strip()

    if expected and client_ip and secrets.compare_digest(provided.encode(), expected.encode()):
        try:
            return str(ipaddress.ip_address(client_ip))
        except ValueError:
            pass
    return meta.get("REMOTE_ADDR")


class ClientIPMixin:
    def get_ident(self, request):
        return get_client_ip(request)


class AnonRateThrottle(ClientIPMixin, throttling.AnonRateThrottle):
    pass


class ScopedRateThrottle(ClientIPMixin, throttling.ScopedRateThrottle):
    pass
