from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.utils.html import format_html

from .models import Category, Dish, Option, OptionGroup, SubCategory
from .services import invalidate_menu_cache


def photo_thumb(obj, height=48):
    if not obj.photo:
        return "—"
    return format_html('<img src="{}" style="height:{}px;border-radius:4px">', obj.photo.url, height)


def fcfa(amount):
    return f"{amount:,} F".replace(",", " ")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "icon", "position", "is_active"]
    list_editable = ["position", "is_active"]
    search_fields = ["name"]
    readonly_fields = ["slug"]


@admin.register(SubCategory)
class SubCategoryAdmin(admin.ModelAdmin):
    list_display = ["thumb", "name", "category", "position", "is_active"]
    list_display_links = ["thumb", "name"]
    list_editable = ["position", "is_active"]
    list_filter = ["category", "is_active"]
    list_select_related = ["category"]
    search_fields = ["name"]
    readonly_fields = ["slug", "preview"]

    @admin.display(description="photo")
    def thumb(self, obj):
        return photo_thumb(obj)

    @admin.display(description="aperçu")
    def preview(self, obj):
        return photo_thumb(obj, height=200)


class OptionGroupInline(admin.TabularInline):
    model = OptionGroup
    extra = 0
    fields = ["name", "min_choices", "max_choices", "position"]
    show_change_link = True  # les options se saisissent dans la fiche du groupe


@admin.register(Dish)
class DishAdmin(admin.ModelAdmin):
    list_display = ["thumb", "name", "subcategory", "price_fcfa", "is_available", "is_featured", "position"]
    list_display_links = ["thumb", "name"]
    list_editable = ["is_available", "is_featured", "position"]
    list_filter = ["subcategory__category", "subcategory", "is_available", "is_featured"]
    list_select_related = ["subcategory"]
    search_fields = ["name", "description"]
    readonly_fields = ["slug", "preview"]
    fields = [
        "name", "slug", "subcategory", "description", "price", "photo", "preview",
        "is_available", "is_featured", "prep_minutes", "position",
    ]
    inlines = [OptionGroupInline]
    actions = ["mark_unavailable", "mark_available"]

    @admin.display(description="photo")
    def thumb(self, obj):
        return photo_thumb(obj)

    @admin.display(description="aperçu")
    def preview(self, obj):
        return photo_thumb(obj, height=200)

    @admin.display(description="prix", ordering="price")
    def price_fcfa(self, obj):
        return fcfa(obj.price)

    @admin.action(description="Mettre en rupture de stock")
    def mark_unavailable(self, request, queryset):
        n = queryset.update(is_available=False)
        invalidate_menu_cache()  # update() ne déclenche pas les signaux
        self.message_user(request, f"{n} plat(s) mis en rupture.", messages.WARNING)

    @admin.action(description="Remettre disponible")
    def mark_available(self, request, queryset):
        n = queryset.update(is_available=True)
        invalidate_menu_cache()
        self.message_user(request, f"{n} plat(s) de nouveau disponible(s).", messages.SUCCESS)


class OptionInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        defaults = sum(
            1 for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE") and form.cleaned_data.get("is_default")
        )
        group = self.instance
        if defaults > group.max_choices:
            raise ValidationError(
                f"{defaults} options sont « choisies par défaut », mais le groupe n'en autorise que {group.max_choices}."
            )


class OptionInline(admin.TabularInline):
    model = Option
    formset = OptionInlineFormSet
    extra = 1
    fields = ["name", "price_delta", "is_default", "is_available", "position"]


@admin.register(OptionGroup)
class OptionGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "dish", "min_choices", "max_choices", "position"]
    list_filter = ["dish__subcategory__category"]
    list_select_related = ["dish"]
    search_fields = ["name", "dish__name"]
    autocomplete_fields = ["dish"]
    inlines = [OptionInline]
