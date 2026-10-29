import pytest
from django.test import RequestFactory, override_settings

from apps.core.throttling import AnonRateThrottle, get_client_ip

KEY = "cle-secrete-de-test"
PROXY_IP = "10.0.0.2"      # le serveur Next.js
VISITOR_IP = "41.202.10.7"  # le vrai visiteur


def make_request(**headers):
    return RequestFactory().get("/api/v1/reservations/", REMOTE_ADDR=PROXY_IP, **headers)


@override_settings(FRONTEND_API_KEY=KEY)
def test_cle_valide_utilise_x_client_ip():
    request = make_request(HTTP_X_FRONTEND_KEY=KEY, HTTP_X_CLIENT_IP=VISITOR_IP)
    assert get_client_ip(request) == VISITOR_IP
    assert AnonRateThrottle().get_ident(request) == VISITOR_IP


@override_settings(FRONTEND_API_KEY=KEY)
def test_cle_absente_ignore_x_client_ip():
    request = make_request(HTTP_X_CLIENT_IP=VISITOR_IP)
    assert get_client_ip(request) == PROXY_IP


@override_settings(FRONTEND_API_KEY=KEY)
def test_cle_fausse_ignore_x_client_ip():
    request = make_request(HTTP_X_FRONTEND_KEY="mauvaise-cle", HTTP_X_CLIENT_IP=VISITOR_IP)
    assert get_client_ip(request) == PROXY_IP


@override_settings(FRONTEND_API_KEY="")
def test_cle_non_configuree_ignore_x_client_ip():
    # Sans FRONTEND_API_KEY, un X-Frontend-Key vide ne doit pas suffire
    request = make_request(HTTP_X_FRONTEND_KEY="", HTTP_X_CLIENT_IP=VISITOR_IP)
    assert get_client_ip(request) == PROXY_IP


@override_settings(FRONTEND_API_KEY=KEY)
@pytest.mark.parametrize("bad_ip", ["pas-une-ip", "1.2.3.4, 5.6.7.8"])
def test_x_client_ip_invalide_ignore(bad_ip):
    request = make_request(HTTP_X_FRONTEND_KEY=KEY, HTTP_X_CLIENT_IP=bad_ip)
    assert get_client_ip(request) == PROXY_IP
