from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import DAYS, RestaurantSettings

TIME_RANGE = {
    "type": "array",
    "items": {"type": "string", "pattern": r"^\d{2}:\d{2}$", "example": "11:00"},
    "minItems": 2,
    "maxItems": 2,
    "description": "[ouverture, fermeture] au format HH:MM",
}


@extend_schema_field({
    "type": "object",
    "description": "Plages d'ouverture par jour. Jour absent ou liste vide = fermé.",
    "properties": {day: {"type": "array", "items": TIME_RANGE} for day in DAYS},
    "additionalProperties": False,
    "example": {"lun": [["11:00", "15:00"], ["18:00", "23:00"]], "dim": []},
})
class OpeningHoursField(serializers.JSONField):
    pass


class PublicSettingsSerializer(serializers.ModelSerializer):
    opening_hours = OpeningHoursField(read_only=True)

    class Meta:
        model = RestaurantSettings
        # reservation_covers_per_slot, rccm, ncc et vat_rate restent internes
        fields = [
            "name", "phone", "whatsapp", "email", "address", "maps_url",
            "opening_hours", "reservation_slot_minutes", "reservation_max_party",
            "catering_min_guests",
        ]
