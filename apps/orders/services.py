"""Sessions de table, commandes et demandes (docs/phase3.md, « Backend : app orders »).
Les prix envoyés par le téléphone sont toujours ignorés : tout est recalculé depuis la carte."""

import datetime as dt

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.menu.models import Dish
from apps.payments.providers import PaymentStatus, get_provider
from apps.tables.models import Table

from . import events
from .models import Event, Order, OrderItem, OrderItemOption, Receipt, ServiceRequest, TableSession

MAX_LINES = 30            # lignes par commande
MAX_QUANTITY = 20         # exemplaires par ligne
MAX_ORDERS_PER_HOUR = 10  # par session
ETA_PER_PREPARING = 2     # minutes ajoutées par commande déjà en préparation
IDLE_HOURS = 6
EVENTS_KEEP_HOURS = 24

S = Order.Status
NEXT_STATUS = {S.RECEIVED: S.PREPARING, S.PREPARING: S.READY, S.READY: S.SERVED}
ADVANCE_ROLES = {
    S.PREPARING: {"kitchen", "manager"},
    S.READY: {"kitchen", "manager"},
    S.SERVED: {"waiter", "cashier", "manager"},
}
TIMESTAMP_FIELD = {S.PREPARING: "accepted_at", S.READY: "ready_at", S.SERVED: "served_at"}
CANCEL_ROLES = {"manager", "cashier"}
CANCELLABLE = {S.RECEIVED, S.PREPARING}
PAY_ROLES = {"cashier", "manager"}
MOBILE_MONEY = {Order.PaymentMethod.WAVE, Order.PaymentMethod.ORANGE_MONEY, Order.PaymentMethod.MTN_MOMO}


def _has_role(user, roles):
    return user.is_superuser or user.role in roles


# --- Sessions -------------------------------------------------------------------------------

def open_session(qr_token):
    """QR inconnu, table inactive ou jeton régénéré → 404 ; sinon la session ouverte de la table, créée au besoin."""
    try:
        table = Table.objects.get(qr_token=qr_token, is_active=True)
    except (Table.DoesNotExist, DjangoValidationError, ValueError):
        raise NotFound("Ce QR code n'est plus valable, demandez au serveur.")
    return session_for_table(table)


@transaction.atomic
def session_for_table(table):
    """Session ouverte de la table ; deux téléphones qui scannent en même temps obtiennent la même."""
    Table.objects.select_for_update().get(pk=table.pk)
    session = TableSession.objects.filter(table=table).exclude(status=TableSession.Status.CLOSED).first()
    return session or TableSession.objects.create(table=table)


def close_session(session, by=None, now=None):
    session.status = TableSession.Status.CLOSED
    session.closed_at = now or timezone.now()
    session.closed_by = by
    session.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])
    return session


def close_idle_sessions(now=None, hours=IDLE_HOURS):
    """Ferme les sessions sans activité depuis 6 h (commande close_idle_sessions, cron cPanel)."""
    now = now or timezone.now()
    idle = TableSession.objects.exclude(status=TableSession.Status.CLOSED).filter(
        last_activity_at__lt=now - dt.timedelta(hours=hours)
    )
    count = 0
    for session in idle:
        close_session(session, now=now)
        count += 1
    return count


def purge_events(hours=EVENTS_KEEP_HOURS):
    """Les écrans rechargent l'état complet par REST à l'ouverture : un événement de plus d'un jour ne sert plus."""
    count, _ = Event.objects.filter(created_at__lt=timezone.now() - dt.timedelta(hours=hours)).delete()
    return count


def _touch(session, now):
    session.last_activity_at = now
    session.save(update_fields=["last_activity_at", "updated_at"])


def _lock_open_session(session):
    session = TableSession.objects.select_for_update().get(pk=session.pk)
    if session.is_closed:
        raise ValidationError({"detail": ["Cette table est fermée. Demandez au serveur."]})
    return session


# --- Commandes ------------------------------------------------------------------------------

def place_order(*, session=None, items, payment_timing=Order.PaymentTiming.END, payment_method="",
                note="", created_by=None, now=None):
    """Envoie une commande en cuisine.
    items : [{"dish_id", "quantity", "option_ids", "note"}]. session=None : saisie au comptoir (created_by obligatoire).
    Erreurs par ligne : ValidationError({"items": [{}, {"dish_id": [...]}, …]}), une entrée par ligne envoyée."""
    now = now or timezone.now()
    if not items:
        raise ValidationError({"items": ["Le panier est vide."]})
    if len(items) > MAX_LINES:
        raise ValidationError({"items": [f"{MAX_LINES} lignes au maximum par commande."]})

    with transaction.atomic():
        if session is not None:
            session = _lock_open_session(session)
            recent = session.orders.filter(created_at__gte=now - dt.timedelta(hours=1)).count()
            if recent >= MAX_ORDERS_PER_HOUR:
                raise ValidationError({"detail": ["Trop de commandes pour cette table. Demandez au serveur."]})

        lines, errors = _price_lines(items)
        if any(errors):
            raise ValidationError({"items": errors})

        preparing = Order.objects.filter(status=S.PREPARING).count()
        order = Order.objects.create(
            number=_next_value("orders_order_number_seq"),
            session=session,
            channel=Order.Channel.TABLE if session else Order.Channel.COUNTER,
            payment_timing=payment_timing,
            payment_method=payment_method,
            total=sum(line["line_total"] for line in lines),
            note=note.strip(),
            eta_minutes=max(line["dish"].prep_minutes for line in lines) + ETA_PER_PREPARING * preparing,
            created_by=created_by,
        )
        for line in lines:
            item = OrderItem.objects.create(
                order=order, dish=line["dish"], dish_name=line["dish"].name, unit_price=line["dish"].price,
                quantity=line["quantity"], options_label=line["options_label"], options_price=line["options_price"],
                note=line["note"], line_total=line["line_total"],
            )
            OrderItemOption.objects.bulk_create(
                OrderItemOption(item=item, option=o, name=o.name, price_delta=o.price_delta) for o in line["options"]
            )
        if session is not None:
            _touch(session, now)
        transaction.on_commit(lambda: events.order_created(order))
    return order


def _price_lines(items):
    """Recharge chaque plat et ses options depuis la base ; renvoie (lignes chiffrées, erreurs par ligne)."""
    dishes = {
        d.id: d
        for d in Dish.objects.filter(id__in=[i.get("dish_id") for i in items])
        .select_related("subcategory__category").prefetch_related("option_groups__options")
    }
    lines, errors = [], []
    for item in items:
        dish = dishes.get(item.get("dish_id"))
        error, line = _price_line(dish, item)
        errors.append(error)
        if line:
            lines.append(line)
    return lines, errors


def _price_line(dish, item):
    if dish is None or not (dish.is_available and dish.subcategory.is_active and dish.subcategory.category.is_active):
        return {"dish_id": ["Ce plat n'est plus disponible."]}, None
    quantity = item.get("quantity", 1)
    if not 1 <= quantity <= MAX_QUANTITY:
        return {"quantity": [f"Entre 1 et {MAX_QUANTITY} exemplaires."]}, None

    available = {o.id: (o, g) for g in dish.option_groups.all() for o in g.options.all()}
    chosen_ids = list(dict.fromkeys(item.get("option_ids", [])))  # sans doublon, ordre conservé
    if any(oid not in available for oid in chosen_ids):
        return {"option_ids": ["Option invalide pour ce plat."]}, None
    chosen = [available[oid] for oid in chosen_ids]
    for option, _ in chosen:
        if not option.is_available:
            return {"option_ids": [f"« {option.name} » n'est plus disponible."]}, None
    for group in dish.option_groups.all():
        count = sum(1 for _, g in chosen if g.id == group.id)
        if count < group.min_choices:
            return {"option_ids": [f"{group.name} : choisissez au moins {group.min_choices} option(s)."]}, None
        if count > group.max_choices:
            return {"option_ids": [f"{group.name} : {group.max_choices} option(s) au maximum."]}, None

    options = [o for o, g in sorted(chosen, key=lambda og: (og[1].position, og[1].id, og[0].position, og[0].id))]
    options_price = sum(o.price_delta for o in options)
    return {}, {
        "dish": dish,
        "quantity": quantity,
        "options": options,
        "options_label": " · ".join(o.name for o in options),
        "options_price": options_price,
        "note": (item.get("note") or "").strip(),
        "line_total": (dish.price + options_price) * quantity,
    }


def _next_value(sequence):
    """Prochain numéro d'une séquence PostgreSQL (commandes, reçus) : jamais réutilisé."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval(%s)", [sequence])
        return cursor.fetchone()[0]


@transaction.atomic
def advance(order, by, now=None):
    """received → preparing → ready (cuisine) → served (serveur, caisse). Le gérant peut tout faire."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    target = NEXT_STATUS.get(order.status)
    if target is None:
        raise ValidationError({"status": [f"Une commande « {order.get_status_display().lower()} » ne peut plus avancer."]})
    if not _has_role(by, ADVANCE_ROLES[target]):
        raise PermissionDenied(f"Votre rôle ne permet pas de passer la commande à « {S(target).label.lower()} ».")
    now = now or timezone.now()
    order.status = target
    setattr(order, TIMESTAMP_FIELD[target], now)
    order.status_changed_by = by
    order.save(update_fields=["status", TIMESTAMP_FIELD[target], "status_changed_by", "updated_at"])
    if order.session_id:
        _touch(order.session, now)
    transaction.on_commit(lambda: events.order_status(order))
    return order


@transaction.atomic
def cancel(order, by, reason, now=None):
    """Gérant ou caisse, tant que la commande n'est pas prête ; motif obligatoire."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if not _has_role(by, CANCEL_ROLES):
        raise PermissionDenied("Seuls le gérant et la caisse peuvent annuler une commande.")
    if order.status not in CANCELLABLE:
        raise ValidationError({"status": ["Une commande prête, servie ou déjà annulée ne peut plus être annulée."]})
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": ["Indiquez le motif de l'annulation."]})
    order.status = S.CANCELLED
    order.cancelled_at = now or timezone.now()
    order.cancel_reason = reason
    order.status_changed_by = by
    order.save(update_fields=["status", "cancelled_at", "cancel_reason", "status_changed_by", "updated_at"])
    transaction.on_commit(lambda: events.order_cancelled(order))
    return order


# --- Demandes de la table -------------------------------------------------------------------

@transaction.atomic
def request_service(session, kind, now=None):
    """Une seule demande ouverte par type ; « bill » passe la session en addition demandée.
    Renvoie (demande, créée ?) : la route répond 201 ou 200."""
    session = _lock_open_session(session)
    now = now or timezone.now()
    existing = session.requests.filter(kind=kind, status=ServiceRequest.Status.OPEN).first()
    if existing:
        return existing, False
    request = ServiceRequest.objects.create(session=session, kind=kind)
    if kind == ServiceRequest.Kind.BILL and session.status == TableSession.Status.OPEN:
        session.status = TableSession.Status.BILL_REQUESTED
        session.save(update_fields=["status", "updated_at"])
    _touch(session, now)
    transaction.on_commit(lambda: events.request_created(request))
    return request, True


@transaction.atomic
def complete_request(request, by, now=None):
    request = ServiceRequest.objects.select_for_update().get(pk=request.pk)
    if request.status == ServiceRequest.Status.DONE:
        return request
    request.status = ServiceRequest.Status.DONE
    request.handled_by = by
    request.handled_at = now or timezone.now()
    request.save(update_fields=["status", "handled_by", "handled_at", "updated_at"])
    transaction.on_commit(lambda: events.request_done(request))
    return request


# --- Encaissement ---------------------------------------------------------------------------

@transaction.atomic
def pay(session, method, transaction_ref, cashier, order_ids=None, now=None):
    """Encaisse tout ou partie de l'addition d'une table (order_ids : seulement ces commandes).
    Quand tout est payé : la session se ferme et ses demandes en attente sont marquées traitées."""
    _check_can_pay(cashier)
    session = TableSession.objects.select_for_update().get(pk=session.pk)
    if session.is_closed:
        raise ValidationError({"detail": ["Cette table est déjà fermée."]})
    unpaid = list(
        session.orders.select_for_update().filter(receipt__isnull=True).exclude(status=S.CANCELLED).order_by("created_at")
    )
    orders = unpaid
    if order_ids is not None:
        wanted = set(order_ids)
        orders = [o for o in unpaid if o.id in wanted]
        if len(orders) != len(wanted):
            raise ValidationError({"order_ids": ["Commande déjà payée, annulée ou d'une autre table."]})

    receipt = _create_receipt(orders, session, method, transaction_ref, cashier, now)
    if len(orders) == len(unpaid):
        close_session(session, by=cashier, now=receipt.paid_at)
        session.requests.filter(status=ServiceRequest.Status.OPEN).update(
            status=ServiceRequest.Status.DONE, handled_by=cashier, handled_at=receipt.paid_at,
        )
    transaction.on_commit(lambda: events.session_paid(session, receipt.reference))
    return receipt


@transaction.atomic
def pay_order(order, method, transaction_ref, cashier, now=None):
    """Encaisse une commande au comptoir (sans table). Une commande de table passe par pay(session)."""
    _check_can_pay(cashier)
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.session_id:
        raise ValidationError({"detail": ["Commande d'une table : encaissez l'addition de la table."]})
    if order.status == S.CANCELLED or order.is_paid:
        raise ValidationError({"detail": ["Cette commande est annulée ou déjà payée."]})
    return _create_receipt([order], None, method, transaction_ref, cashier, now)


def _check_can_pay(user):
    if not _has_role(user, PAY_ROLES):
        raise PermissionDenied("Seuls la caisse et le gérant peuvent encaisser.")


def _create_receipt(orders, session, method, transaction_ref, cashier, now):
    if not orders:
        raise ValidationError({"detail": ["Rien à encaisser."]})
    if method not in Order.PaymentMethod.values:
        raise ValidationError({"method": ["Moyen de paiement inconnu."]})
    transaction_ref = (transaction_ref or "").strip()
    if method in MOBILE_MONEY and not transaction_ref:
        raise ValidationError({"transaction_ref": ["Indiquez la référence de la transaction Mobile Money."]})

    total = sum(o.total for o in orders)
    provider = get_provider()
    initiation = provider.initiate({"total": total, "method": method, "transaction_ref": transaction_ref, "orders": orders})
    if provider.verify(initiation.provider_ref) != PaymentStatus.PAID:
        raise ValidationError({"detail": ["Le paiement n'est pas confirmé."]})

    receipt = Receipt.objects.create(
        number=_next_value("orders_receipt_number_seq"),
        session=session, total=total, method=method, provider=provider.code,
        transaction_ref=transaction_ref, paid_at=now or timezone.now(), cashier=cashier,
    )
    Order.objects.filter(pk__in=[o.pk for o in orders]).update(receipt=receipt)
    return receipt
