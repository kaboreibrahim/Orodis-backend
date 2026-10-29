from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

from .models import RestaurantSettings

admin.site.site_header = "Les Délices d'Orodis"
admin.site.site_title = "Orodis gestion"
admin.site.index_title = "Administration"


@admin.register(RestaurantSettings)
class RestaurantSettingsAdmin(admin.ModelAdmin):
    fieldsets = [
        ("Coordonnées", {"fields": ["name", "phone", "whatsapp", "email", "address", "maps_url"]}),
        ("Horaires", {"fields": ["opening_hours"]}),
        ("Réservations", {"fields": ["reservation_slot_minutes", "reservation_max_party", "reservation_covers_per_slot"]}),
        ("Traiteur", {"fields": ["catering_min_guests"]}),
        ("Mentions légales (reçus)", {"fields": ["rccm", "ncc", "vat_rate"], "classes": ["collapse"]}),
    ]

    def changelist_view(self, request, extra_context=None):
        # Pas de liste : on ouvre directement l'unique ligne
        obj = RestaurantSettings.load()
        return redirect(reverse("admin:core_restaurantsettings_change", args=[obj.pk]))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
