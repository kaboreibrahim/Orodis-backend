from django import forms
from django.contrib import admin

from .models import CateringFormula, QuoteRequest


class CateringFormulaForm(forms.ModelForm):
    items = forms.CharField(
        label="contenu", required=False, widget=forms.Textarea(attrs={"rows": 8}),
        help_text="Une ligne par élément de la formule.",
    )

    class Meta:
        model = CateringFormula
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial["items"] = "\n".join(self.instance.items)

    def clean_items(self):
        return [line.strip() for line in self.cleaned_data["items"].splitlines() if line.strip()]


@admin.register(CateringFormula)
class CateringFormulaAdmin(admin.ModelAdmin):
    form = CateringFormulaForm
    list_display = ["name", "price_from", "is_highlighted", "is_active", "position"]
    list_editable = ["price_from", "is_highlighted", "is_active", "position"]
    readonly_fields = ["slug"]


@admin.register(QuoteRequest)
class QuoteRequestAdmin(admin.ModelAdmin):
    list_display = ["reference", "event_type", "event_date", "guests", "formula", "name", "whatsapp", "status"]
    list_filter = ["status", "event_type", "formula"]
    search_fields = ["reference", "name", "whatsapp", "email"]
    date_hierarchy = "event_date"
    list_select_related = ["formula"]
    readonly_fields = ["reference", "created_at"]

    def has_add_permission(self, request):
        return False
