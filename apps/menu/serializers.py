from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Category, Dish, Option, OptionGroup, SubCategory


class OptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Option
        fields = ["id", "name", "price_delta", "is_default"]


class OptionGroupSerializer(serializers.ModelSerializer):
    options = OptionSerializer(many=True, read_only=True)

    class Meta:
        model = OptionGroup
        fields = ["id", "name", "min_choices", "max_choices", "options"]


class DishSerializer(serializers.ModelSerializer):
    option_groups = OptionGroupSerializer(many=True, read_only=True)

    class Meta:
        model = Dish
        fields = [
            "id", "slug", "name", "description", "price", "photo",
            "is_featured", "prep_minutes", "option_groups",
        ]


class DishDetailSerializer(DishSerializer):
    """Fiche d'un plat ou plat mis en avant : on y ajoute où il se trouve dans la carte."""

    subcategory = serializers.CharField(source="subcategory.name", read_only=True)
    category = serializers.SlugField(source="subcategory.category.slug", read_only=True)

    class Meta(DishSerializer.Meta):
        fields = [*DishSerializer.Meta.fields, "subcategory", "category"]


class SubCategorySerializer(serializers.ModelSerializer):
    dishes = DishSerializer(many=True, read_only=True)

    class Meta:
        model = SubCategory
        fields = ["id", "slug", "name", "photo", "dishes"]


class CategorySerializer(serializers.ModelSerializer):
    subcategories = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "slug", "name", "icon", "subcategories"]

    @extend_schema_field(SubCategorySerializer(many=True))
    def get_subcategories(self, category):
        # Une sous-catégorie sans plat disponible n'est pas affichée
        subs = [s for s in category.subcategories.all() if s.dishes.all()]
        return SubCategorySerializer(subs, many=True, context=self.context).data


class DishAvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Dish
        fields = ["id", "name", "is_available"]
        read_only_fields = ["id", "name"]
        extra_kwargs = {"is_available": {"required": True}}


class StaffDishSerializer(serializers.ModelSerializer):
    """Plat vu par le personnel (écran cuisine, ruptures) : disponible ou non, avec sa place dans la carte."""

    category = serializers.CharField(source="subcategory.category.name", read_only=True)
    subcategory = serializers.CharField(source="subcategory.name", read_only=True)

    class Meta:
        model = Dish
        fields = ["id", "name", "category", "subcategory", "is_available"]


# --- Gestion de la carte (gérant) ---

class ManageOptionSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False, help_text="Absent pour une nouvelle option.")

    class Meta:
        model = Option
        fields = ["id", "name", "price_delta", "is_default", "is_available"]


class ManageOptionGroupSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False, help_text="Absent pour un nouveau groupe.")
    options = ManageOptionSerializer(many=True)

    class Meta:
        model = OptionGroup
        fields = ["id", "name", "min_choices", "max_choices", "options"]

    def validate(self, data):
        if data.get("max_choices", 1) < 1:
            raise serializers.ValidationError({"max_choices": "Le maximum doit être au moins 1."})
        if data.get("min_choices", 0) > data.get("max_choices", 1):
            raise serializers.ValidationError({"min_choices": "Le minimum ne peut pas dépasser le maximum."})
        if not data.get("options"):
            raise serializers.ValidationError({"options": "Ajoutez au moins une option à ce groupe."})
        if data.get("min_choices", 0) > len(data["options"]):
            raise serializers.ValidationError({"min_choices": "Il n'y a pas assez d'options pour ce minimum."})
        return data


class ManageDishSerializer(serializers.ModelSerializer):
    """Plat complet pour l'écran « Carte & menus ». La photo s'envoie à part (…/photo/).
    option_groups, s'il est fourni, remplace tous les groupes du plat : ceux qui manquent sont supprimés."""

    option_groups = ManageOptionGroupSerializer(many=True, required=False)

    class Meta:
        model = Dish
        fields = ["id", "slug", "name", "description", "price", "photo", "subcategory", "is_available", "is_featured",
                  "prep_minutes", "position", "option_groups"]
        read_only_fields = ["slug", "photo", "position"]

    def validate_price(self, value):
        if value % 5:
            raise serializers.ValidationError("Le prix doit être un multiple de 5 F.")
        return value

    def create(self, validated_data):
        from . import services

        return services.save_dish(None, validated_data)

    def update(self, instance, validated_data):
        from . import services

        return services.save_dish(instance, validated_data)


class ManageSubCategorySerializer(serializers.ModelSerializer):
    dishes = ManageDishSerializer(many=True, read_only=True)

    class Meta:
        model = SubCategory
        fields = ["id", "slug", "name", "category", "photo", "is_active", "position", "dishes"]
        read_only_fields = ["slug", "photo", "position"]


class ManageCategorySerializer(serializers.ModelSerializer):
    subcategories = ManageSubCategorySerializer(many=True, read_only=True)

    class Meta:
        model = Category
        fields = ["id", "slug", "name", "icon", "is_active", "position", "subcategories"]
        read_only_fields = ["slug", "position"]


class PhotoSerializer(serializers.Serializer):
    photo = serializers.ImageField(help_text="JPEG, PNG ou WebP, 5 Mo au plus ; convertie en WebP.")

    def validate_photo(self, file):
        from apps.core.utils import MAX_UPLOAD_BYTES

        if file.size > MAX_UPLOAD_BYTES:
            raise serializers.ValidationError("L'image ne doit pas dépasser 5 Mo.")
        return file


class ReorderSerializer(serializers.Serializer):
    level = serializers.ChoiceField(choices=["category", "subcategory", "dish"])
    ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False,
                                help_text="Tous les éléments du même parent, dans le nouvel ordre.")
