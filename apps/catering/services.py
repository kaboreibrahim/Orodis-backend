import json
import logging
import re
from urllib.parse import quote as urlquote

from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import formats, timezone
from rest_framework.exceptions import ValidationError
from rest_framework.renderers import JSONRenderer

from apps.core.models import RestaurantSettings
from apps.core.utils import normalize_ci_phone

from .models import QuoteRequest
from .selectors import active_formulas

logger = logging.getLogger(__name__)

FORMULAS_CACHE_KEY = "catering:formulas"
FORMULAS_CACHE_TTL = 60 * 10


# --- Formules -----------------------------------------------------------------------------

def get_public_formulas():
    from .serializers import PublicFormulaSerializer  # évite l'import circulaire

    data = cache.get(FORMULAS_CACHE_KEY)
    if data is None:
        data = json.loads(JSONRenderer().render(PublicFormulaSerializer(active_formulas(), many=True).data))
        cache.set(FORMULAS_CACHE_KEY, data, FORMULAS_CACHE_TTL)
    return data


def invalidate_formulas_cache():
    transaction.on_commit(lambda: cache.delete(FORMULAS_CACHE_KEY))


# --- Demandes de devis --------------------------------------------------------------------

def create_quote(*, event_type, event_date, guests, place_type, name, whatsapp,
                 formula=None, place_detail="", email="", message="", now=None):
    """Enregistre la demande ; l'e-mail au restaurant part après validation de la transaction.
    Renvoie (demande, lien wa.me vers le restaurant ou None)."""
    if event_date < timezone.localdate(now):
        raise ValidationError({"event_date": ["La date de l'événement est déjà passée."]})
    if formula is not None and not formula.is_active:
        raise ValidationError({"formula": ["Cette formule n'est plus proposée."]})
    whatsapp = normalize_ci_phone(whatsapp, field="whatsapp")
    RestaurantSettings.load()

    with transaction.atomic():
        rs = RestaurantSettings.objects.select_for_update().get(pk=1)  # numérotation sans doublon
        if guests < rs.catering_min_guests:
            raise ValidationError(
                {"guests": [f"Nos prestations traiteur commencent à partir de {rs.catering_min_guests} invités."]}
            )
        quote = QuoteRequest.objects.create(
            reference=_next_reference(event_date),
            event_type=event_type, event_date=event_date, guests=guests,
            place_type=place_type, place_detail=place_detail.strip(), formula=formula,
            name=name.strip(), whatsapp=whatsapp, email=email, message=message.strip(),
        )
        transaction.on_commit(lambda: send_quote_email(quote.pk))

    return quote, restaurant_whatsapp_url(quote, rs)


def update_quote(quote, *, status=None, internal_note=None):
    fields = ["updated_at"]
    if status is not None:
        quote.status = status
        fields.append("status")
    if internal_note is not None:
        quote.internal_note = internal_note
        fields.append("internal_note")
    quote.save(update_fields=fields)
    return quote


def _next_reference(day):
    """D-JJMM-NNNN, numéroté par date d'événement (appelé sous le verrou des réglages)."""
    prefix = f"D-{day:%d%m}-"
    last = (
        QuoteRequest.objects.filter(reference__startswith=prefix)
        .order_by("-reference").values_list("reference", flat=True).first()
    )
    seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


# --- Messages -----------------------------------------------------------------------------

def _summary(quote):
    place = quote.get_place_type_display() + (f" — {quote.place_detail}" if quote.place_detail else "")
    lines = [
        f"Événement : {quote.get_event_type_display()}, le {formats.date_format(quote.event_date, 'l j F Y')}",
        f"Invités : {quote.guests}",
        f"Lieu : {place}",
        f"Formule : {quote.formula.name if quote.formula else 'Indécis'}",
    ]
    if quote.message:
        lines.append(f"Message : {quote.message}")
    return lines


def restaurant_whatsapp_url(quote, rs):
    """Lien que le client ouvre pour écrire au restaurant, pré-rempli avec sa demande."""
    number = re.sub(r"\D", "", rs.whatsapp)
    if not number:
        return None
    if len(number) == 10:
        number = f"225{number}"
    text = (
        f"Bonjour, je viens d'envoyer une demande de devis traiteur (réf. {quote.reference}) :\n"
        + "\n".join(f"• {line}" for line in _summary(quote))
        + f"\nNom : {quote.name}"
    )
    return f"https://wa.me/{number}?text={urlquote(text)}"


def send_quote_email(quote_id):
    """E-mail récapitulatif au restaurant. Une panne SMTP est journalisée, jamais remontée au client."""
    recipient = settings.RESTAURANT_NOTIFY_EMAIL
    if not recipient:
        return False
    quote = QuoteRequest.objects.select_related("formula").get(pk=quote_id)
    body = "\n".join([
        f"Nouvelle demande de devis {quote.reference}",
        "",
        *_summary(quote),
        "",
        f"Nom : {quote.name}",
        f"WhatsApp : {quote.whatsapp}",
        f"E-mail : {quote.email or '—'}",
    ])
    message = EmailMessage(
        subject=(
            f"Devis {quote.reference} — {quote.get_event_type_display()} "
            f"le {formats.date_format(quote.event_date, 'j F Y')}, {quote.guests} invités"
        ),
        body=body,
        to=[recipient],
        reply_to=[quote.email] if quote.email else None,
    )
    try:
        message.send()
        return True
    except Exception:
        logger.exception("Échec de l'envoi de l'e-mail du devis %s", quote.reference)
        return False
