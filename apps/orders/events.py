"""Événements temps réel (docs/phase3.md, tableau « Événements »), relus par les écrans en polling.
Appelés par les services dans transaction.on_commit : jamais d'événement pour un changement annulé.
Ils ne portent que de quoi mettre l'écran à jour ; l'écran recharge l'état complet par REST à chaque ouverture."""

import json
import logging

from rest_framework.renderers import JSONRenderer

from .models import Event, Order

logger = logging.getLogger(__name__)

A = Event.Audience
TIMESTAMP = {"preparing": "accepted_at", "ready": "ready_at", "served": "served_at"}


def _send(audiences, event, data, session_id=None):
    """Une ligne par destinataire ; une erreur d'écriture ne doit jamais faire échouer une commande."""
    rows = [Event(audience=audience, kind=event, data=data) for audience in audiences]
    if session_id:
        rows.append(Event(audience=A.SESSION, session_id=session_id, kind=event, data=data))
    try:
        Event.objects.bulk_create(rows)
    except Exception:
        logger.exception("Événement %s non publié", event)


def order_created(order):
    from .serializers import StaffOrderSerializer  # évite l'import circulaire services ↔ serializers

    order = (Order.objects.select_related("session__table", "created_by", "status_changed_by", "receipt")
             .prefetch_related("items__options").get(pk=order.pk))
    data = json.loads(JSONRenderer().render(StaffOrderSerializer(order).data))
    _send([A.STAFF, A.KITCHEN], "order.created", data)


def order_status(order):
    at = getattr(order, TIMESTAMP.get(order.status, "updated_at"))
    data = {"id": order.id, "number": order.number, "status": order.status, "at": at.isoformat()}
    _send([A.STAFF, A.KITCHEN], "order.status", data, order.session_id)


def order_cancelled(order):
    data = {"id": order.id, "number": order.number, "reason": order.cancel_reason}
    _send([A.STAFF, A.KITCHEN], "order.cancelled", data, order.session_id)


def request_created(request):
    data = {"id": request.id, "table_number": request.session.table.number, "kind": request.kind}
    _send([A.STAFF], "request.created", data)


def request_done(request):
    _send([A.STAFF], "request.done", {"id": request.id, "kind": request.kind}, request.session_id)


def session_paid(session, receipt_number):
    """Appelé par le service pay() de l'étape B4."""
    _send([A.STAFF], "session.paid", {"receipt": receipt_number}, session.pk)


def dish_availability(dish):
    data = {"dish_id": dish.id, "is_available": dish.is_available}
    _send([A.STAFF, A.KITCHEN, A.TABLES], "dish.availability", data)
