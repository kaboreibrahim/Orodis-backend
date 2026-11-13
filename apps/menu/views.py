from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasRole

from . import selectors, services
from .models import Dish
from .serializers import CategorySerializer, DishAvailabilitySerializer, DishDetailSerializer, StaffDishSerializer


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
