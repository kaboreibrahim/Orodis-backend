import datetime as dt

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import Event, Order, Receipt, ServiceRequest, TableSession

ACTIVE = [Order.Status.RECEIVED, Order.Status.PREPARING, Order.Status.READY]
EVENTS_LIMIT = 100  # au-delà, l'écran récupère la suite au prochain appel


def session_state(session):
    """Ce que le téléphone affiche : commandes avec leurs lignes, demandes ouvertes, addition en cours."""
    orders = list(session.orders.select_related("receipt").prefetch_related("items").order_by("-created_at"))
    return {
        "table": session.table,
        "status": session.status,
        "orders": orders,
        "open_requests": list(session.requests.filter(status=ServiceRequest.Status.OPEN)),
        "total": sum(o.total for o in orders if o.status != Order.Status.CANCELLED),
    }


def table_order(session, number):
    """Commande de CETTE session uniquement : un numéro seul ne suffit jamais."""
    return session.orders.select_related("receipt").prefetch_related("items").filter(number=number).first()


def staff_orders(user, *, status=None, channel=None, date=None, table=None):
    """Commandes pour la gestion ; la cuisine ne voit que les commandes actives.
    status : un ou plusieurs statuts séparés par des virgules. date : AAAA-MM-JJ, jour de la commande à Abidjan."""
    qs = (Order.objects.select_related("session__table", "created_by", "status_changed_by", "receipt")
          .prefetch_related("items__options").order_by("-created_at"))
    if user.role == "kitchen" and not user.is_superuser:
        qs = qs.filter(status__in=ACTIVE)
    if status:
        qs = qs.filter(status__in=status.split(","))
    if channel:
        qs = qs.filter(channel=channel)
    if date:
        start = timezone.make_aware(dt.datetime.combine(date, dt.time.min))
        qs = qs.filter(created_at__gte=start, created_at__lt=start + dt.timedelta(days=1))
    if table:
        qs = qs.filter(session__table__number=table)
    return qs


def receipt(number, session=None):
    """Reçu avec ses commandes et lignes ; session donnée = reçu de cette table uniquement."""
    qs = Receipt.objects.select_related("session__table", "cashier").prefetch_related("orders__items")
    if session is not None:
        qs = qs.filter(session=session)
    return qs.filter(number=number).first()


def staff_requests(status=ServiceRequest.Status.OPEN):
    qs = ServiceRequest.objects.select_related("session__table", "handled_by").order_by("created_at")
    return qs.filter(status=status) if status else qs


def open_sessions(status=None):
    """Tables occupées : commandes et montant en cours (hors annulations), demandes en attente."""
    qs = TableSession.objects.exclude(status=TableSession.Status.CLOSED) if status is None else TableSession.objects.filter(status=status)
    qs = qs.select_related("table__zone").prefetch_related("requests").annotate(
        orders_count=Count("orders", filter=~Q(orders__status=Order.Status.CANCELLED)),
        total=Sum("orders__total", filter=~Q(orders__status=Order.Status.CANCELLED), default=0),
    ).order_by("table__number")
    sessions = list(qs)
    for session in sessions:
        session.open_requests = [r.kind for r in session.requests.all() if r.status == ServiceRequest.Status.OPEN]
    return sessions


def latest_event_id():
    return Event.objects.order_by("-id").values_list("id", flat=True).first() or 0


def table_events(session, after):
    """Événements de cette table, plus ceux envoyés à toutes les tables (plats en rupture)."""
    return _events(Q(audience=Event.Audience.TABLES) | Q(audience=Event.Audience.SESSION, session=session), after)


def staff_events(user, after):
    """La cuisine a son propre flux : jamais deux fois le même événement."""
    audience = Event.Audience.KITCHEN if user.role == "kitchen" else Event.Audience.STAFF
    return _events(Q(audience=audience), after)


def _events(condition, after):
    return list(Event.objects.filter(condition, id__gt=after).order_by("id")[:EVENTS_LIMIT])
