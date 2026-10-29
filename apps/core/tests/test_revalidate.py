import json
import urllib.error
from unittest import mock

import pytest

from apps.catering.models import CateringFormula
from apps.core import services
from apps.core.models import RestaurantSettings
from apps.menu.models import Category
from apps.menu.services import invalidate_menu_cache

pytestmark = pytest.mark.django_db
URL = "https://site.test/api/revalidate"
SECRET = "s3cret"


@pytest.fixture
def revalidate_on(settings):
    settings.FRONTEND_REVALIDATE_URL = URL
    settings.REVALIDATE_SECRET = SECRET


@pytest.fixture
def posted(revalidate_on, monkeypatch):
    """Remplace l'appel HTTP : enregistre les tags envoyés."""
    calls = []
    monkeypatch.setattr(services, "_post_revalidate", lambda url, tags: calls.append(tags))
    return calls


# --- notify_frontend_revalidate -------------------------------------------------------------

def test_post_apres_commit_avec_secret_et_timeout(revalidate_on, django_capture_on_commit_callbacks):
    with mock.patch("apps.core.services.urllib.request.urlopen") as urlopen:
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            services.notify_frontend_revalidate(["menu"])
        urlopen.assert_not_called()  # rien n'est envoyé avant le commit
        for callback in callbacks:
            callback()

    request = urlopen.call_args.args[0]
    assert (request.full_url, request.get_method()) == (URL, "POST")
    assert request.get_header("X-revalidate-secret") == SECRET
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {"tags": ["menu"]}
    assert urlopen.call_args.kwargs["timeout"] == 3


def test_url_vide_ne_fait_rien(settings, django_capture_on_commit_callbacks):
    settings.FRONTEND_REVALIDATE_URL = ""
    with mock.patch("apps.core.services.urllib.request.urlopen") as urlopen:
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            services.notify_frontend_revalidate(["menu"])
    assert callbacks == []
    urlopen.assert_not_called()


@pytest.mark.parametrize("error", [
    urllib.error.URLError("Connection refused"),
    urllib.error.HTTPError(URL, 401, "Unauthorized", {}, None),
    TimeoutError("timed out"),
])
def test_site_injoignable_journalise_sans_lever(revalidate_on, django_capture_on_commit_callbacks, caplog, error):
    with mock.patch("apps.core.services.urllib.request.urlopen", side_effect=error):
        with django_capture_on_commit_callbacks(execute=True):
            services.notify_frontend_revalidate(["settings"])  # ne doit pas lever
    assert "Revalidation Next.js impossible" in caplog.text
    assert caplog.records[-1].levelname == "WARNING"


# --- Branchements -------------------------------------------------------------------------

def test_signal_carte(posted, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        Category.objects.create(name="Boissons")
    assert ["menu"] in posted


def test_rupture_de_stock_via_admin(posted, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        invalidate_menu_cache()  # appelée par les actions admin après update()
    assert posted == [["menu"]]


def test_signal_reglages(posted, django_capture_on_commit_callbacks):
    rs = RestaurantSettings.load()
    with django_capture_on_commit_callbacks(execute=True):
        rs.phone = "0700000000"
        rs.save()
    assert posted == [["settings"]]


def test_signal_formules(posted, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        CateringFormula.objects.create(name="Buffet")
    assert posted == [["catering"]]
