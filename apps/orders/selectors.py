import datetime as dt

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import Event, Order, OrderItem, Receipt, ServiceRequest, TableSession

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


# --- Tableau de bord du gérant -----------------------------------------------------------------

PERIOD_DAYS = {"today": 1, "week": 7, "month": 30}
TREND_DAYS = 7
TOP_DISHES = 5


def _day_start(day):
    return timezone.make_aware(dt.datetime.combine(day, dt.time.min))


def _sales(start, end):
    """Encaissé (reçus) et commandes passées (hors annulations) entre deux instants."""
    paid = Receipt.objects.filter(paid_at__gte=start, paid_at__lt=end).aggregate(total=Sum("total", default=0), count=Count("id"))
    orders = Order.objects.filter(created_at__gte=start, created_at__lt=end)
    return {
        "revenue": paid["total"],
        "receipts_count": paid["count"],
        "orders_count": orders.exclude(status=Order.Status.CANCELLED).count(),
        "cancelled_count": orders.filter(status=Order.Status.CANCELLED).count(),
        "average_ticket": paid["total"] // paid["count"] if paid["count"] else 0,
    }


def dashboard(period="today", today=None):
    """Vue d'ensemble : la période demandée et la précédente de même durée, les 7 derniers jours,
    les moyens de paiement, les plats les plus vendus et l'état de la salle à l'instant.
    Les recettes sont comptées au jour de l'encaissement, les commandes au jour où elles sont passées."""
    today = today or timezone.localdate()
    days = PERIOD_DAYS[period]
    end = _day_start(today) + dt.timedelta(days=1)
    start = end - dt.timedelta(days=days)

    receipts = Receipt.objects.filter(paid_at__gte=start, paid_at__lt=end)
    labels = dict(Order.PaymentMethod.choices)
    by_method = [
        {"method": row["method"], "label": labels.get(row["method"], row["method"]), "total": row["total"], "count": row["count"]}
        for row in receipts.values("method").annotate(total=Sum("total"), count=Count("id")).order_by("-total")
    ]

    trend_start = end - dt.timedelta(days=TREND_DAYS)
    tz = timezone.get_current_timezone()
    revenue_by_day = dict(Receipt.objects.filter(paid_at__gte=trend_start, paid_at__lt=end)
                          .annotate(day=TruncDate("paid_at", tzinfo=tz)).values("day")
                          .annotate(total=Sum("total")).values_list("day", "total"))
    orders_by_day = dict(Order.objects.filter(created_at__gte=trend_start, created_at__lt=end)
                         .exclude(status=Order.Status.CANCELLED)
                         .annotate(day=TruncDate("created_at", tzinfo=tz)).values("day")
                         .annotate(count=Count("id")).values_list("day", "count"))
    trend = []
    for offset in range(TREND_DAYS - 1, -1, -1):
        day = today - dt.timedelta(days=offset)
        trend.append({"date": day, "revenue": revenue_by_day.get(day, 0), "orders_count": orders_by_day.get(day, 0)})

    top_dishes = list(
        OrderItem.objects.filter(order__created_at__gte=start, order__created_at__lt=end)
        .exclude(order__status=Order.Status.CANCELLED)
        .values("dish_id", "dish_name").annotate(quantity=Sum("quantity"), revenue=Sum("line_total"))
        .order_by("-quantity", "-revenue", "dish_name")[:TOP_DISHES]
    )

    from apps.menu.models import Dish  # import local : menu n'importe pas orders, on garde ce sens unique
    from apps.tables.models import Table

    unpaid = Order.objects.filter(receipt__isnull=True).exclude(status=Order.Status.CANCELLED)
    return {
        "period": period,
        "start": start.astimezone(tz).date(),
        "end": today,
        "current": _sales(start, end),
        "previous": _sales(start - dt.timedelta(days=days), start),
        "by_method": by_method,
        "trend": trend,
        "top_dishes": top_dishes,
        "live": {
            "tables_total": Table.objects.filter(is_active=True).count(),
            "tables_open": TableSession.objects.exclude(status=TableSession.Status.CLOSED).count(),
            "active_orders": Order.objects.filter(status__in=ACTIVE).count(),
            "open_requests": ServiceRequest.objects.filter(status=ServiceRequest.Status.OPEN).count(),
            "to_collect": unpaid.aggregate(total=Sum("total", default=0))["total"],
            "unavailable_dishes": list(Dish.objects.filter(is_available=False).order_by("name").values_list("name", flat=True)),
        },
    }


# --- Paiements du jour (caisse, gérant) -------------------------------------------------------

def payments(day=None):
    """Les encaissements d'une journée : reçus du plus récent au plus ancien, totaux par moyen de paiement
    (les quatre moyens sont toujours présents, à zéro s'il le faut) et ce qui reste à encaisser maintenant."""
    day = day or timezone.localdate()
    start = _day_start(day)
    end = start + dt.timedelta(days=1)
    receipts = (Receipt.objects.filter(paid_at__gte=start, paid_at__lt=end)
                .select_related("session__table", "cashier").annotate(orders_count=Count("orders")).order_by("-paid_at"))

    sums = {row["method"]: row for row in Receipt.objects.filter(paid_at__gte=start, paid_at__lt=end)
            .values("method").annotate(total=Sum("total"), count=Count("id"))}
    by_method = [
        {"method": value, "label": label, "total": sums.get(value, {}).get("total", 0), "count": sums.get(value, {}).get("count", 0)}
        for value, label in Order.PaymentMethod.choices
    ]

    unpaid = (Order.objects.filter(receipt__isnull=True).exclude(status=Order.Status.CANCELLED)
              .values("session__table__number").annotate(total=Sum("total"), orders_count=Count("id"))
              .order_by("session__table__number"))
    tables = [{"table_number": row["session__table__number"], "total": row["total"], "orders_count": row["orders_count"]} for row in unpaid]

    return {
        "date": day,
        "revenue": sum(m["total"] for m in by_method),
        "receipts_count": sum(m["count"] for m in by_method),
        "by_method": by_method,
        "to_collect": {"total": sum(t["total"] for t in tables), "tables": tables},
        "receipts": receipts,
    }
