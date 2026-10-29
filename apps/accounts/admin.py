from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ["username", "first_name", "last_name", "role", "is_active", "last_login"]
    list_filter = ["role", "is_active", "is_staff"]
    fieldsets = [
        *DjangoUserAdmin.fieldsets,
        ("Restaurant", {"fields": ["role", "phone"]}),
    ]
    add_fieldsets = [
        *DjangoUserAdmin.add_fieldsets,
        ("Restaurant", {"fields": ["first_name", "last_name", "role", "phone"]}),
    ]
