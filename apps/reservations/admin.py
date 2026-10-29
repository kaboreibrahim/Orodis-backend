from django.contrib import admin

from .models import Reservation


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ["reference", "date", "time", "party_size", "name", "phone", "status", "source", "table"]
    list_filter = ["status", "source", "date"]
    search_fields = ["reference", "name", "phone"]
    date_hierarchy = "date"
    list_select_related = ["table"]
    readonly_fields = ["reference", "status", "source", "handled_by", "handled_at", "refusal_reason", "created_at"]

    def has_add_permission(self, request):
        return False  # création et changements de statut via le tableau de bord (règles de services.py)
