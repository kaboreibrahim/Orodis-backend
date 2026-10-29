from rest_framework import serializers

from apps.core.utils import normalize_ci_phone
from apps.tables.models import Table

from .models import Reservation

HHMM = "%H:%M"


# --- Public -------------------------------------------------------------------------------

class AvailabilityQuerySerializer(serializers.Serializer):
    date = serializers.DateField()
    party = serializers.IntegerField(min_value=1)


class SlotSerializer(serializers.Serializer):
    time = serializers.TimeField(format=HHMM)
    available = serializers.BooleanField()


class AvailabilitySerializer(serializers.Serializer):
    date = serializers.DateField()
    party = serializers.IntegerField()
    closed = serializers.BooleanField()
    max_party = serializers.IntegerField()
    slots = SlotSerializer(many=True)


class ReservationCreateSerializer(serializers.Serializer):
    date = serializers.DateField()
    time = serializers.TimeField(input_formats=[HHMM])
    party_size = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=30)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate_phone(self, value):
        try:
            return normalize_ci_phone(value)
        except serializers.ValidationError as exc:
            raise serializers.ValidationError(exc.detail["phone"])


class ReservationPublicSerializer(serializers.ModelSerializer):
    """Réponse au site : jamais le nom ni le téléphone."""

    time = serializers.TimeField(format=HHMM)

    class Meta:
        model = Reservation
        fields = ["reference", "status", "date", "time", "party_size"]


# --- Personnel ----------------------------------------------------------------------------

class ReservationStaffSerializer(serializers.ModelSerializer):
    time = serializers.TimeField(format=HHMM)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    table_number = serializers.IntegerField(source="table.number", read_only=True, default=None)
    handled_by = serializers.StringRelatedField()

    class Meta:
        model = Reservation
        fields = [
            "id", "reference", "date", "time", "party_size", "name", "phone", "note",
            "status", "status_display", "source", "table", "table_number",
            "handled_by", "handled_at", "refusal_reason", "created_at",
        ]
        read_only_fields = fields


class StaffReservationCreateSerializer(ReservationCreateSerializer):
    source = serializers.ChoiceField(
        choices=[Reservation.Source.PHONE, Reservation.Source.WALK_IN], default=Reservation.Source.PHONE
    )


class ConfirmSerializer(serializers.Serializer):
    table_id = serializers.PrimaryKeyRelatedField(
        queryset=Table.objects.all(), source="table", required=False, allow_null=True
    )


class RefuseSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class ActionResultSerializer(serializers.Serializer):
    reservation = ReservationStaffSerializer()
    whatsapp_url = serializers.URLField(allow_null=True)
