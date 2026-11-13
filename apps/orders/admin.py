from django.contrib import admin

from .models import Order, OrderItem, OrderItemOption, Receipt, ServiceRequest, TableSession


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    fields = ["quantity", "dish_name", "options_label", "unit_price", "options_price", "note", "line_total"]
    readonly_fields = fields


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["number", "channel", "session", "status", "total", "payment_timing", "receipt", "created_at"]
    list_filter = ["status", "channel", "payment_timing", "created_at"]
    search_fields = ["number"]
    readonly_fields = [f.name for f in Order._meta.fields]
    inlines = [OrderItemInline]

    def has_add_permission(self, request):
        return False  # une commande se crée par l'API, avec ses prix recalculés


@admin.register(TableSession)
class TableSessionAdmin(admin.ModelAdmin):
    list_display = ["table", "status", "created_at", "last_activity_at", "closed_at"]
    list_filter = ["status", "table__zone"]
    readonly_fields = ["token", "created_at", "last_activity_at", "closed_at", "closed_by"]


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = ["session", "kind", "status", "created_at", "handled_by", "handled_at"]
    list_filter = ["kind", "status"]


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ["reference", "session", "total", "method", "transaction_ref", "paid_at", "cashier"]
    list_filter = ["method", "paid_at"]
    search_fields = ["number", "transaction_ref"]
    readonly_fields = [f.name for f in Receipt._meta.fields]

    def has_add_permission(self, request):
        return False  # un reçu se crée à l'encaissement, par l'API


admin.site.register(OrderItemOption)
