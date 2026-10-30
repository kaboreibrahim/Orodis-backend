import json
import threading
import urllib.error
from unittest import mock

import pytest
from django.db import transaction

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
    """Remplace le lancement du thread : enregistre les tags de chaque POST."""
    calls = []
    monkeypatch.setattr(services, "_start_post", lambda url, tags: calls.append(tags))
    return calls


@pytest.fixture
def sync_thread(monkeypatch):
    """Thread exécuté immédiatement, pour vérifier la requête HTTP sans attente."""
    started = []

    class ImmediateThread:
        def __init__(self, *, target, args, daemon, name):
            self.target, self.args, self.daemon = target, args, daemon

        def start(self):
            started.append(self)
            self.target(*self.args)

    monkeypatch.setattr(services, "Thread", ImmediateThread)
    return started


# --- Requête HTTP -------------------------------------------------------------------------

def test_post_apres_commit_dans_un_thread_demon(revalidate_on, sync_thread, django_capture_on_commit_callbacks):
    with mock.patch("apps.core.services.urllib.request.urlopen") as urlopen:
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            services.notify_frontend_revalidate(["menu"])
        urlopen.assert_not_called()  # rien n'est envoyé avant le commit
        for callback in callbacks:
            callback()

    assert [t.daemon for t in sync_thread] == [True]
    request = urlopen.call_args.args[0]
    assert (request.full_url, request.get_method()) == (URL, "POST")
    assert request.get_header("X-revalidate-secret") == SECRET
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {"tags": ["menu"]}
    assert urlopen.call_args.kwargs["timeout"] == 3


def test_site_lent_ne_bloque_pas_le_commit(revalidate_on, django_capture_on_commit_callbacks):
    release, done = threading.Event(), threading.Event()

    def slow_urlopen(request, timeout):
        release.wait(5)
        done.set()
        return mock.MagicMock()

    with mock.patch("apps.core.services.urllib.request.urlopen", side_effect=slow_urlopen):
        with django_capture_on_commit_callbacks(execute=True):
            services.notify_frontend_revalidate(["menu"])
        assert not done.is_set()  # le commit est rendu sans attendre le site
        release.set()
        assert done.wait(5)


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
def test_site_injoignable_journalise_sans_lever(revalidate_on, sync_thread, django_capture_on_commit_callbacks,
                                               caplog, error):
    with mock.patch("apps.core.services.urllib.request.urlopen", side_effect=error):
        with django_capture_on_commit_callbacks(execute=True):
            services.notify_frontend_revalidate(["settings"])  # ne doit pas lever
    assert "Revalidation Next.js impossible" in caplog.text
    assert caplog.records[-1].levelname == "WARNING"


# --- Regroupement par transaction -----------------------------------------------------------

def test_un_seul_post_par_transaction(posted, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        services.notify_frontend_revalidate(["menu"])
        services.notify_frontend_revalidate(["settings", "menu"])
        services.notify_frontend_revalidate(["catering"])
    assert len(callbacks) == 1
    assert posted == [["menu", "settings", "catering"]]


def test_tags_annules_par_rollback(posted, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(RuntimeError), transaction.atomic():
            services.notify_frontend_revalidate(["menu"])
            raise RuntimeError
        services.notify_frontend_revalidate(["settings"])
    assert posted == [["settings"]]


def test_transactions_successives_envoient_chacune(posted, django_capture_on_commit_callbacks):
    for tag in ("menu", "catering"):
        with django_capture_on_commit_callbacks(execute=True):
            services.notify_frontend_revalidate([tag])
    assert posted == [["menu"], ["catering"]]


# --- Branchements -------------------------------------------------------------------------

def test_signal_carte(posted, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        Category.objects.create(name="Boissons")
    assert posted == [["menu"]]


def test_rupture_de_stock_via_admin(posted, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        invalidate_menu_cache()  # appelée par les actions admin après update()
    assert posted == [["menu"]]


def test_signal_reglages(posted, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):  # la création du singleton envoie son propre lot
        rs = RestaurantSettings.load()
    posted.clear()
    with django_capture_on_commit_callbacks(execute=True):
        rs.phone = "0700000000"
        rs.save()
    assert posted == [["settings"]]


def test_signal_formules(posted, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        CateringFormula.objects.create(name="Buffet")
    assert posted == [["catering"]]
