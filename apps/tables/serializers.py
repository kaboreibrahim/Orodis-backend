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
