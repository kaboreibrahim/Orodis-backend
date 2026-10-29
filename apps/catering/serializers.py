from rest_framework import serializers

from apps.core.utils import normalize_ci_phone

from .models import CateringFormula, QuoteRequest


class PublicFormulaSerializer(serializers.ModelSerializer):
    items = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = CateringFormula
        fields = ["slug", "name", "description", "price_from", "items", "is_highlighted"]


class QuoteCreateSerializer(serializers.Serializer):
    event_type = serializers.ChoiceField(choices=QuoteRequest.EventType.choices)
    event_date = serializers.DateField()
    guests = serializers.IntegerField(min_value=1)
    place_type = serializers.ChoiceField(choices=QuoteRequest.PlaceType.choices)
    place_detail = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    formula = serializers.CharField(max_length=60, help_text="Slug d'une formule, ou « indecis ».")
    name = serializers.CharField(max_length=100)
    whatsapp = serializers.CharField(max_length=30)
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    message = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")

    def validate_formula(self, value):
        if value == "indecis":
            return None
        formula = CateringFormula.objects.filter(slug=value, is_active=True).first()
        if formula is None:
            raise serializers.ValidationError("Formule inconnue. Choisissez une formule de la liste ou « indecis ».")
        return formula

    def validate_whatsapp(self, value):
        try:
            return normalize_ci_phone(value, field="whatsapp")
        except serializers.ValidationError as exc:
            raise serializers.ValidationError(exc.detail["whatsapp"])


class QuoteCreatedSerializer(serializers.Serializer):
    reference = serializers.CharField()
    whatsapp_url = serializers.URLField(allow_null=True)


class QuoteStaffSerializer(serializers.ModelSerializer):
    event_type_display = serializers.CharField(source="get_event_type_display", read_only=True)
    place_type_display = serializers.CharField(source="get_place_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    formula_name = serializers.CharField(source="formula.name", read_only=True, default="Indécis")

    class Meta:
        model = QuoteRequest
        fields = [
            "id", "reference", "event_type", "event_type_display", "event_date", "guests",
            "place_type", "place_type_display", "place_detail", "formula", "formula_name",
            "name", "whatsapp", "email", "message", "status", "status_display", "internal_note",
            "created_at", "updated_at",
        ]
        # Seuls le statut et la note interne se modifient (PATCH)
        read_only_fields = [f for f in fields if f not in ("status", "internal_note")]
