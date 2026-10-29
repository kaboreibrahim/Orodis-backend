import datetime as dt
from urllib.parse import unquote

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.catering import services
from apps.catering.models import CateringFormula

pytestmark = pytest.mark.django_db
NOTIFY = "orodistraiteur@gmail.com"


def test_create_quote_reference_telephone_et_lien(restaurant, quote_data):
    quote, url = services.create_quote(**quote_data)
    assert quote.reference == f"D-{quote_data['event_date']:%d%m}-0001"
    assert quote.whatsapp == "+2250707070707"
    assert quote.status == "new"
    assert url.startswith("https://wa.me/2250700000000?text=")
    assert quote.reference in unquote(url) and "Formule : Buffet" in unquote(url)

    second, _ = services.create_quote(**quote_data)
    assert second.reference.endswith("-0002")


def test_create_quote_formule_indecise(restaurant, quote_data):
    quote, url = services.create_quote(**{**quote_data, "formula": None})
    assert quote.formula is None
    assert "Formule : Indécis" in unquote(url)


def test_trop_peu_d_invites(restaurant, quote_data):
    with pytest.raises(ValidationError) as exc:
        services.create_quote(**{**quote_data, "guests": 19})
    assert "20 invités" in str(exc.value.detail["guests"][0])


def test_date_passee(restaurant, quote_data):
    with pytest.raises(ValidationError) as exc:
        services.create_quote(**{**quote_data, "event_date": timezone.localdate() - dt.timedelta(days=1)})
    assert "déjà passée" in str(exc.value.detail["event_date"][0])


def test_formule_inactive_refusee(restaurant, quote_data, buffet):
    buffet.is_active = False
    buffet.save()
    with pytest.raises(ValidationError) as exc:
        services.create_quote(**quote_data)
    assert "formula" in exc.value.detail


def test_pas_de_lien_sans_whatsapp_du_restaurant(restaurant, quote_data):
    restaurant.whatsapp = ""
    restaurant.save()
    _, url = services.create_quote(**quote_data)
    assert url is None


@override_settings(RESTAURANT_NOTIFY_EMAIL=NOTIFY)
def test_email_envoye_apres_commit(restaurant, quote_data, django_capture_on_commit_callbacks, mailoutbox):
    with django_capture_on_commit_callbacks(execute=True):
        quote, _ = services.create_quote(**quote_data)
    assert len(mailoutbox) == 1
    mail = mailoutbox[0]
    assert mail.to == [NOTIFY]
    assert quote.reference in mail.subject and "150 invités" in mail.subject
    assert mail.reply_to == ["awa@example.com"]
    assert "+2250707070707" in mail.body and "Cocody" in mail.body


@override_settings(RESTAURANT_NOTIFY_EMAIL=NOTIFY)
def test_email_attend_le_commit(restaurant, quote_data, django_capture_on_commit_callbacks, mailoutbox):
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        services.create_quote(**quote_data)
    assert len(callbacks) == 1
    assert mailoutbox == []


@override_settings(RESTAURANT_NOTIFY_EMAIL="")
def test_pas_d_email_sans_destinataire(restaurant, quote_data, mailoutbox):
    quote, _ = services.create_quote(**quote_data)
    assert services.send_quote_email(quote.pk) is False
    assert mailoutbox == []


@override_settings(RESTAURANT_NOTIFY_EMAIL=NOTIFY)
def test_panne_smtp_journalisee_sans_erreur(restaurant, quote_data, monkeypatch, caplog):
    quote, _ = services.create_quote(**quote_data)

    def broken_send(self):
        raise OSError("SMTP indisponible")

    monkeypatch.setattr("django.core.mail.EmailMessage.send", broken_send)
    assert services.send_quote_email(quote.pk) is False
    assert "Échec de l'envoi" in caplog.text


def test_update_quote(restaurant, quote_data):
    quote, _ = services.create_quote(**quote_data)
    services.update_quote(quote, status="contacted", internal_note="Rappeler lundi")
    quote.refresh_from_db()
    assert (quote.status, quote.internal_note) == ("contacted", "Rappeler lundi")


def test_formules_en_cache_et_videes(buffet, django_assert_num_queries, django_capture_on_commit_callbacks):
    CateringFormula.objects.create(name="Ancienne", is_active=False)
    with django_assert_num_queries(1):
        assert [f["slug"] for f in services.get_public_formulas()] == ["buffet"]
    with django_assert_num_queries(0):
        services.get_public_formulas()
    with django_capture_on_commit_callbacks(execute=True):
        buffet.name = "Grand buffet"
        buffet.save()
    assert services.get_public_formulas()[0]["name"] == "Grand buffet"


def test_seed_formulas_relancable(db):
    call_command("seed_formulas")
    call_command("seed_formulas")
    formulas = list(CateringFormula.objects.all())
    assert [f.name for f in formulas] == ["Cocktail dînatoire", "Buffet", "Dîner servi"]
    assert [f.is_highlighted for f in formulas] == [False, True, False]
    assert all(f.price_from is None for f in formulas)
