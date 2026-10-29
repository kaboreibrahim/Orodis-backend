from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import selectors, services
from .serializers import CategorySerializer, DishDetailSerializer


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
