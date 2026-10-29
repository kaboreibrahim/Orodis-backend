from rest_framework import serializers

from .models import RestaurantSettings


class PublicSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = RestaurantSettings
        fields = [
            "name", "phone", "whatsapp", "email", "address", "maps_url",
            "opening_hours", "reservation_slot_minutes", "reservation_max_party",
        ]
