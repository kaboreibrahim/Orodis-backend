from django.contrib import admin, messages

from . import services
from .models import Table, Zone


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ["name", "position"]
    list_editable = ["position"]


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ["number", "zone", "seats", "is_active", "qr_version"]
    list_editable = ["seats", "is_active"]
    list_filter = ["zone", "is_active"]
    readonly_fields = ["qr_url", "qr_version"]
    fields = ["number", "zone", "seats", "is_active", "qr_url", "qr_version"]
    actions = ["regenerate_qr"]

    @admin.display(description="adresse du QR")
    def qr_url(self, obj):
        return obj.qr_url if obj.pk else "—"

    @admin.action(description="Régénérer le QR (l'ancien chevalet ne fonctionnera plus)")
    def regenerate_qr(self, request, queryset):
        for table in queryset:
            services.regenerate_qr(table)
        self.message_user(request, f"{queryset.count()} QR régénéré(s). Pensez à réimprimer les chevalets.", messages.WARNING)
