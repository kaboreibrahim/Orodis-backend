from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasRole, IsManager

from . import selectors, services
from .models import Category, Dish, SubCategory
from .serializers import (
    CategorySerializer, DishAvailabilitySerializer, DishDetailSerializer, ManageCategorySerializer,
    ManageDishSerializer, ManageSubCategorySerializer, PhotoSerializer, ReorderSerializer, StaffDishSerializer,
)


class PublicMenuMixin:
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []  # lectures légères ou en cache, appelées par le serveur Next.js


class MenuView(PublicMenuMixin, APIView):
    @extend_schema(responses=CategorySerializer(many=True), summary="Carte complète (plats disponibles)")
    def get(self, request):
        return Response(services.get_public_menu(request))


class DishDetailView(PublicMenuMixin, APIView):
    @extend_schema(responses=DishDetailSerializer, summary="Fiche d'un plat avec ses options")
    def get(self, request, slug):
        dish = selectors.public_dish(slug)
        if dish is None:
            raise NotFound("Ce plat n'existe pas ou n'est plus disponible.")
        return Response(DishDetailSerializer(dish, context={"request": request}).data)


class FeaturedDishesView(PublicMenuMixin, ListAPIView):
    serializer_class = DishDetailSerializer
    pagination_class = None

    def get_queryset(self):
        return selectors.featured_dishes()

    @extend_schema(summary="Plats mis en avant sur l'accueil")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class DishAvailabilityView(APIView):
    """Rupture de stock en un clic, depuis la caisse, la cuisine ou le tableau de bord du gérant."""

    permission_classes = [HasRole("manager", "cashier", "kitchen")]

    @extend_schema(request=DishAvailabilitySerializer, responses=DishAvailabilitySerializer, summary="Plat disponible ou en rupture")
    def patch(self, request, pk):
        dish = get_object_or_404(Dish, pk=pk)
        serializer = DishAvailabilitySerializer(dish, data=request.data)
        serializer.is_valid(raise_exception=True)
        dish = services.set_dish_availability(dish, serializer.validated_data["is_available"])
        return Response(DishAvailabilitySerializer(dish).data)


class StaffDishListView(ListAPIView):
    """Tous les plats, en rupture compris, dans l'ordre de la carte : liste des ruptures de l'écran cuisine."""

    permission_classes = [HasRole("manager", "cashier", "kitchen")]
    serializer_class = StaffDishSerializer
    pagination_class = None

    def get_queryset(self):
        return Dish.objects.select_related("subcategory__category").order_by(
            "subcategory__category__position", "subcategory__category__name",
            "subcategory__position", "subcategory__name", "position", "name",
        )

    @extend_schema(summary="Tous les plats avec leur disponibilité (personnel)")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


# --- Gestion de la carte (gérant) ---

class ManageMenuView(APIView):
    permission_classes = [IsManager]

    @extend_schema(responses=ManageCategorySerializer(many=True), summary="Toute la carte, éléments masqués compris (gérant)")
    def get(self, request):
        return Response(ManageCategorySerializer(selectors.manage_menu(), many=True, context={"request": request}).data)


class ManageReorderView(APIView):
    permission_classes = [IsManager]

    @extend_schema(request=ReorderSerializer, responses={204: None}, summary="Changer l'ordre d'affichage")
    def post(self, request):
        serializer = ReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.reorder(**serializer.validated_data)
        except ValueError as error:
            return Response({"ids": [str(error)]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ManageViewSet(viewsets.ModelViewSet):
    """Créer, modifier, supprimer. La lecture de la carte se fait d'un coup par ManageMenuView."""

    permission_classes = [IsManager]
    pagination_class = None
    http_method_names = ["post", "patch", "put", "delete"]
    protected_message = "Cet élément est encore utilisé."

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response({"detail": self.protected_message}, status=status.HTTP_400_BAD_REQUEST)


class PhotoMixin:
    @extend_schema(methods=["put"], request={"multipart/form-data": PhotoSerializer}, summary="Envoyer la photo")
    @extend_schema(methods=["delete"], request=None, summary="Retirer la photo")
    @action(detail=True, methods=["put", "delete"], parser_classes=[MultiPartParser])
    def photo(self, request, pk=None):
        instance = self.get_object()
        file = None
        if request.method == "PUT":
            serializer = PhotoSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            file = serializer.validated_data["photo"]
        services.set_photo(instance, file)
        return Response(self.get_serializer(instance).data)


class ManageCategoryViewSet(ManageViewSet):
    serializer_class = ManageCategorySerializer
    queryset = Category.objects.all()
    protected_message = "Cette catégorie contient encore des sous-catégories : supprimez-les ou déplacez-les d'abord."

    def perform_create(self, serializer):
        services.create_in_order(serializer)


class ManageSubCategoryViewSet(PhotoMixin, ManageViewSet):
    serializer_class = ManageSubCategorySerializer
    queryset = SubCategory.objects.all()
    protected_message = "Cette sous-catégorie contient encore des plats : supprimez-les ou déplacez-les d'abord."

    def perform_create(self, serializer):
        services.create_in_order(serializer)


class ManageDishViewSet(PhotoMixin, ManageViewSet):
    serializer_class = ManageDishSerializer
    queryset = Dish.objects.prefetch_related("option_groups__options")
    protected_message = "Ce plat figure dans des commandes : il ne peut pas être supprimé. Mettez-le en rupture pour le retirer de la carte."
