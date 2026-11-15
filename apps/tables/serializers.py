from rest_framework import serializers

from .models import Table, Zone


class ZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = Zone
        fields = ["id", "name", "position"]


class TableSerializer(serializers.ModelSerializer):
    zone_name = serializers.CharField(source="zone.name", read_only=True)
    qr_url = serializers.CharField(read_only=True)

    class Meta:
        model = Table
        fields = ["id", "number", "zone", "zone_name", "seats", "is_active", "qr_url", "qr_version"]
        read_only_fields = ["qr_version"]


class TableRangeSerializer(serializers.Serializer):
    """Création d'un lot de tables : numéros first, first+1… dans la même zone."""

    first = serializers.IntegerField(min_value=1, max_value=999, help_text="Numéro de la première table.")
    count = serializers.IntegerField(min_value=1, max_value=30, help_text="Nombre de tables à créer.")
    zone = serializers.PrimaryKeyRelatedField(queryset=Zone.objects.all())
    seats = serializers.IntegerField(min_value=1, max_value=30, default=4)
    is_active = serializers.BooleanField(default=True)
