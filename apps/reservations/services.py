import datetime as dt
from urllib.parse import quote

from django.db import transaction
from django.utils import formats, timezone
from rest_framework.exceptions import ValidationError

from apps.core.models import DAYS, RestaurantSettings
from apps.core.utils import normalize_ci_phone

from .models import ACTIVE_STATUSES, Reservation

Status = Reservation.Status
BOOKING_WINDOW_DAYS = 60
LAST_SLOT_BEFORE_CLOSE = dt.timedelta(minutes=60)

TRANSITIONS = {
    Status.PENDING: {Status.CONFIRMED, Status.REFUSED},
    Status.CONFIRMED: {Status.CANCELLED, Status.COMPLETED, Status.NO_SHOW},
}


# --- Disponibilités -------------------------------------------------------------------------

def available_slots(day, party, now=None):
    """Créneaux du jour avec available: true/false. Lève ValidationError (date, party)."""
    now = timezone.localtime(now)
    rs = RestaurantSettings.load()
    _check_request(day, party, rs, now.date(), party_field="party")
    slots = _day_slots(day, rs)
    taken = _covers_by_time(day)
    return {
        "date": day,
        "party": party,
        "closed": not slots,
        "max_party": rs.reservation_max_party,
        "slots": [
            {"time": t, "available": _is_open_slot(day, t, now) and taken.get(t, 0) + party <= rs.reservation_covers_per_slot}
            for t in slots
        ],
    }


def _check_request(day, party, rs, today, party_field="party_size"):
    if day < today:
        raise ValidationError({"date": ["Cette date est déjà passée."]})
    if day > today + dt.timedelta(days=BOOKING_WINDOW_DAYS):
        raise ValidationError({"date": [f"Les réservations sont ouvertes au plus {BOOKING_WINDOW_DAYS} jours à l'avance."]})
    if party < 1:
        raise ValidationError({party_field: ["Indiquez au moins une personne."]})
    if party > rs.reservation_max_party:
        raise ValidationError(
            {party_field: [
                f"Au-delà de {rs.reservation_max_party} personnes, faites une demande de devis sur notre page Traiteur."
            ]},
            code="party_too_large",
        )


def _day_slots(day, rs):
    """Heures de début des créneaux : chaque plage découpée, dernier créneau 60 min avant la fermeture."""
    step = dt.timedelta(minutes=rs.reservation_slot_minutes or 30)
    slots = set()
    for start, end in rs.opening_hours.get(DAYS[day.weekday()], []):
        t = dt.datetime.combine(day, dt.time.fromisoformat(start))
        last = dt.datetime.combine(day, dt.time.fromisoformat(end)) - LAST_SLOT_BEFORE_CLOSE
        while t <= last:
            slots.add(t.time())
            t += step
    return sorted(slots)


def _covers_by_time(day):
    totals = {}
    for t, size in Reservation.objects.filter(date=day, status__in=ACTIVE_STATUSES).values_list("time", "party_size"):
        totals[t] = totals.get(t, 0) + size
    return totals


def _is_open_slot(day, t, now):
    return timezone.make_aware(dt.datetime.combine(day, t)) > now


# --- Création -------------------------------------------------------------------------------

def create_reservation(*, date, time, party_size, name, phone, note="", source=Reservation.Source.SITE,
                       created_by=None, now=None):
    """Site : statut pending, toutes les règles. Personnel (created_by) : statut confirmed,
    le gérant peut forcer un créneau complet, passé ou hors grille, ou un grand groupe."""
    now = timezone.localtime(now)
    phone = normalize_ci_phone(phone)
    staff = created_by is not None
    RestaurantSettings.load()  # crée la ligne si besoin, hors du verrou

    with transaction.atomic():
        # Verrou sur la ligne unique des réglages : les créations passent une par une,
        # même sur un créneau encore vide (aucune ligne de réservation à verrouiller).
        rs = RestaurantSettings.objects.select_for_update().get(pk=1)
        if staff:
            if date < now.date():
                raise ValidationError({"date": ["Cette date est déjà passée."]})
        else:
            _check_request(date, party_size, rs, now.date())
            if time not in _day_slots(date, rs):
                raise ValidationError({"time": ["Ce créneau n'est pas proposé ce jour-là."]})
            if not _is_open_slot(date, time, now):
                raise ValidationError({"time": ["Ce créneau est déjà passé."]})
            taken = sum(
                Reservation.objects.select_for_update()
                .filter(date=date, time=time, status__in=ACTIVE_STATUSES)
                .values_list("party_size", flat=True)
            )
            if taken + party_size > rs.reservation_covers_per_slot:
                raise ValidationError({"time": ["Ce créneau vient d'être complet, choisissez-en un autre."]})

        return Reservation.objects.create(
            reference=_next_reference(date),
            date=date, time=time, party_size=party_size,
            name=name.strip(), phone=phone, note=note.strip(),
            source=source,
            status=Status.CONFIRMED if staff else Status.PENDING,
            handled_by=created_by,
            handled_at=now if staff else None,
        )


def _next_reference(day):
    """R-JJMM-NNNN, numéroté par date de réservation (appelé sous le verrou des réglages)."""
    prefix = f"R-{day:%d%m}-"
    last = (
        Reservation.objects.filter(reference__startswith=prefix)
        .order_by("-reference").values_list("reference", flat=True).first()
    )
    seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


# --- Cycle de vie ---------------------------------------------------------------------------

def confirm_reservation(reservation, by, table=None):
    if table is not None and not table.is_active:
        raise ValidationError({"table_id": ["Cette table est désactivée."]})
    reservation = _transition(reservation, Status.CONFIRMED, by, table=table)
    return reservation, notify(reservation, "confirmed")


def refuse_reservation(reservation, by, reason):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": ["Le motif du refus est obligatoire."]})
    reservation = _transition(reservation, Status.REFUSED, by, refusal_reason=reason)
    return reservation, notify(reservation, "refused")


def cancel_reservation(reservation, by):
    reservation = _transition(reservation, Status.CANCELLED, by)
    return reservation, notify(reservation, "cancelled")


def mark_no_show(reservation, by):
    return _transition(reservation, Status.NO_SHOW, by), None


def complete_reservation(reservation, by):
    return _transition(reservation, Status.COMPLETED, by), None


@transaction.atomic
def _transition(reservation, target, by, **fields):
    reservation = Reservation.objects.select_for_update().get(pk=reservation.pk)
    if target not in TRANSITIONS.get(reservation.status, set()):
        raise ValidationError(
            {"status": [
                f"Impossible de passer une réservation « {reservation.get_status_display()} » "
                f"à « {Status(target).label} »."
            ]},
            code="invalid_transition",
        )
    for name, value in fields.items():
        setattr(reservation, name, value)
    reservation.status = target
    reservation.handled_by = by
    reservation.handled_at = timezone.now()
    reservation.save()
    return reservation


# --- Messages au client ---------------------------------------------------------------------

MESSAGES = {
    "confirmed": (
        "Bonjour {name}, votre réservation aux Délices d'Orodis est confirmée :\n"
        "{date} à {time}, {party} (réf. {reference}).\nÀ très vite !"
    ),
    "refused": (
        "Bonjour {name}, nous sommes désolés : nous ne pouvons pas accepter votre réservation "
        "du {date} à {time} ({party}, réf. {reference}).\nMotif : {reason}\n"
        "N'hésitez pas à choisir un autre créneau."
    ),
    "cancelled": (
        "Bonjour {name}, votre réservation aux Délices d'Orodis du {date} à {time} "
        "(réf. {reference}) a été annulée. Contactez-nous pour convenir d'une autre date."
    ),
}


def notify(reservation, event):
    """Phase 2 : renvoie le lien wa.me pré-rempli (ou None si l'événement n'a pas de message).
    Un fournisseur SMS pourra être branché ici sans toucher aux vues."""
    template = MESSAGES.get(event)
    if template is None:
        return None
    n = reservation.party_size
    text = template.format(
        name=reservation.name,
        date=formats.date_format(reservation.date, "l j F"),  # « samedi 28 novembre »
        time=reservation.time.strftime("%Hh%M"),
        party=f"{n} personne{'s' if n > 1 else ''}",
        reference=reservation.reference,
        reason=reservation.refusal_reason,
    )
    return f"https://wa.me/{reservation.phone.lstrip('+')}?text={quote(text)}"
