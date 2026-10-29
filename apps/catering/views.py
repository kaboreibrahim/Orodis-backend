from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasRole
from apps.core.throttling import ScopedRateThrottle

from . import selectors, services
from .serializers import PublicFormulaSerializer, QuoteCreatedSerializer, QuoteCreateSerializer, QuoteStaffSerializer


class FormulaListView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []  # en cache, appelée par le serveur Next.js

    @extend_schema(responses=PublicFormulaSerializer(many=True), summary="Formules traiteur")
    def get(self, request):
        return Response(services.get_public_formulas())


class QuoteCreateView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "quotes"

    @extend_schema(request=QuoteCreateSerializer, responses={201: QuoteCreatedSerializer},
                   summary="Demande de devis traiteur")
    def post(self, request):
        serializer = QuoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quote, whatsapp_url = services.create_quote(**serializer.validated_data)
        return Response({"reference": quote.reference, "whatsapp_url": whatsapp_url}, status=status.HTTP_201_CREATED)


class QuoteManageViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = QuoteStaffSerializer
    permission_classes = [HasRole("cashier", "manager")]
    filterset_fields = ["status"]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return selectors.staff_quotes()

    @extend_schema(request=QuoteStaffSerializer, responses=QuoteStaffSerializer,
                   summary="Changer le statut ou la note interne")
    def partial_update(self, request, pk=None):
        quote = self.get_object()
        serializer = QuoteStaffSerializer(quote, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        quote = services.update_quote(quote, **serializer.validated_data)
        return Response(QuoteStaffSerializer(quote).data)
