from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.models import RestaurantSettings

from . import services
from .models import Event, Order, OrderItem, OrderItemOption, Receipt, ServiceRequest, TableSession


# --- Entrées --------------------------------------------------------------------------------

class OpenSessionSerializer(serializers.Serializer):
    qr_token = serializers.CharField(max_length=64)


class OrderLineInputSerializer(serializers.Serializer):
    dish_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=services.MAX_QUANTITY, default=1)
    option_ids = serializers.ListField(child=serializers.IntegerField(), default=list, max_length=20)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class PlaceOrderSerializer(serializers.Serializer):
    items = OrderLineInputSerializer(many=True, allow_empty=False, max_length=services.MAX_LINES)
    payment_timing = serializers.ChoiceField(choices=Order.PaymentTiming.choices, default=Order.PaymentTiming.END)
    payment_method = serializers.ChoiceField(choices=Order.PaymentMethod.choices, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class ServiceRequestInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=ServiceRequest.Kind.choices)


# --- Sorties --------------------------------------------------------------------------------

class TableInfoSerializer(serializers.Serializer):
    number = serializers.IntegerField()
    zone = serializers.CharField(source="zone.name")


class SessionOpenedSerializer(serializers.Serializer):
    session_token = serializers.CharField(source="token")
    table = TableInfoSerializer()
    status = serializers.ChoiceField(choices=TableSession.Status.choices)


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ["dish_name", "quantity", "unit_price", "options_label", "options_price", "note", "line_total"]


class TableOrderSerializer(serializers.ModelSerializer):
    """Commande vue par le téléphone : jamais qui l'a traitée."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    receipt_number = serializers.IntegerField(
        source="receipt.number", read_only=True, default=None,
        help_text="Numéro du reçu une fois la commande payée ; null avant.",
    )

    class Meta:
        model = Order
        fields = [
            "number", "status", "status_display", "payment_timing", "payment_method", "total", "eta_minutes",
            "note", "items", "created_at", "accepted_at", "ready_at", "served_at", "cancelled_at", "cancel_reason",
            "receipt_number",
        ]


class ServiceRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceRequest
        fields = ["id", "kind", "status", "created_at"]


class SessionStateSerializer(serializers.Serializer):
    table = TableInfoSerializer()
    status = serializers.ChoiceField(choices=TableSession.Status.choices)
    orders = TableOrderSerializer(many=True)
    open_requests = ServiceRequestSerializer(many=True)
    total = serializers.IntegerField(help_text="Addition en cours : commandes non annulées.")


# --- Personnel ------------------------------------------------------------------------------

class OrderItemOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItemOption
        fields = ["name", "price_delta"]


class StaffOrderItemSerializer(OrderItemSerializer):
    options = OrderItemOptionSerializer(many=True, read_only=True)

    class Meta(OrderItemSerializer.Meta):
        fields = ["id", "dish", *OrderItemSerializer.Meta.fields, "options"]


class StaffOrderSerializer(serializers.ModelSerializer):
    """Commande vue par le personnel : table, lignes détaillées, qui l'a saisie et qui l'a fait avancer."""

    table_number = serializers.IntegerField(source="session.table.number", read_only=True, default=None)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    channel_display = serializers.CharField(source="get_channel_display", read_only=True)
    created_by = serializers.StringRelatedField()
    status_changed_by = serializers.StringRelatedField()
    items = StaffOrderItemSerializer(many=True, read_only=True)
    receipt_number = serializers.IntegerField(
        source="receipt.number", read_only=True, default=None,
        help_text="Numéro du reçu une fois la commande payée ; null avant.",
    )

    class Meta:
        model = Order
        fields = [
            "id", "number", "channel", "channel_display", "session", "table_number", "status", "status_display",
            "payment_timing", "payment_method", "total", "eta_minutes", "note", "items",
            "created_at", "accepted_at", "ready_at", "served_at", "cancelled_at", "cancel_reason",
            "created_by", "status_changed_by", "receipt_number",
        ]


class StaffPlaceOrderSerializer(PlaceOrderSerializer):
    table_number = serializers.IntegerField(
        required=False, allow_null=True, default=None,
        help_text="Table sans téléphone ; vide = commande au comptoir.",
    )


class CancelOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class StaffServiceRequestSerializer(serializers.ModelSerializer):
    table_number = serializers.IntegerField(source="session.table.number", read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    handled_by = serializers.StringRelatedField()

    class Meta:
        model = ServiceRequest
        fields = ["id", "session", "table_number", "kind", "kind_display", "status", "created_at", "handled_by", "handled_at"]


class OpenSessionSummarySerializer(serializers.ModelSerializer):
    table = TableInfoSerializer()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    orders_count = serializers.IntegerField()
    total = serializers.IntegerField(help_text="Montant en cours : commandes non annulées.")
    open_requests = serializers.ListField(child=serializers.CharField(), help_text="Types de demandes en attente.")

    class Meta:
        model = TableSession
        fields = ["id", "table", "status", "status_display", "created_at", "last_activity_at",
                  "orders_count", "total", "open_requests"]


# --- Encaissement et reçus ----------------------------------------------------------------

class PaySerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=Order.PaymentMethod.choices)
    transaction_ref = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    order_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=False,
                                      help_text="Seulement ces commandes ; absent = toute l'addition.")


class ReceiptOrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = ["number", "total", "items"]


class ReceiptSerializer(serializers.ModelSerializer):
    """Données communes aux trois reçus : écran (F3), ticket 80 mm (F5) et PDF A4."""

    reference = serializers.CharField(read_only=True)
    method_display = serializers.CharField(source="get_method_display", read_only=True)
    table_number = serializers.IntegerField(source="session.table.number", read_only=True, default=None)
    cashier = serializers.SerializerMethodField()
    orders = ReceiptOrderSerializer(many=True, read_only=True)

    class Meta:
        model = Receipt
        fields = ["number", "reference", "total", "method", "method_display", "transaction_ref", "paid_at",
                  "table_number", "cashier", "orders"]

    def get_cashier(self, receipt) -> str:
        return (receipt.cashier.first_name or receipt.cashier.username) if receipt.cashier else ""


class ReceiptLegalSerializer(serializers.Serializer):
    rccm = serializers.CharField()
    ncc = serializers.CharField()
    vat_rate = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)


class StaffReceiptSerializer(ReceiptSerializer):
    """Reçu vu par la caisse : en plus, les mentions légales du ticket 80 mm (vides tant que non saisies)."""

    legal = serializers.SerializerMethodField()

    class Meta(ReceiptSerializer.Meta):
        fields = [*ReceiptSerializer.Meta.fields, "legal"]

    @extend_schema_field(ReceiptLegalSerializer)
    def get_legal(self, receipt):
        rs = RestaurantSettings.load()
        return ReceiptLegalSerializer({"rccm": rs.rccm, "ncc": rs.ncc, "vat_rate": rs.vat_rate}).data


class EventSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="kind")

    class Meta:
        model = Event
        fields = ["id", "type", "data"]


class EventsSerializer(serializers.Serializer):
    cursor = serializers.IntegerField(help_text="À renvoyer dans ?after= au prochain appel.")
    events = EventSerializer(many=True)
