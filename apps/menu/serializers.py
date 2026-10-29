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
