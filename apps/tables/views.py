from django.db.models import ProtectedError
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.permissions import IsManager

from . import printing, services
from .models import Table, Zone
from .serializers import TableSerializer, ZoneSerializer


class ZoneViewSet(viewsets.ModelViewSet):
    serializer_class = ZoneSerializer
    permission_classes = [IsManager]
    pagination_class = None  # quelques zones : la liste tient en une réponse
    queryset = Zone.objects.all()

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {"detail": "Cette zone contient encore des tables : déplacez-les ou supprimez-les d'abord."},
                status=status.HTTP_400_BAD_REQUEST,
            )


class TableViewSet(viewsets.ModelViewSet):
    serializer_class = TableSerializer
    permission_classes = [IsManager]
    pagination_class = None
    filterset_fields = ["zone", "is_active", "number"]
    queryset = Table.objects.select_related("zone")

    @extend_schema(request=None, responses=TableSerializer, summary="Nouveau QR : l'ancien chevalet ne fonctionne plus")
    @action(detail=True, methods=["post"], url_path="regenerate-qr")
    def regenerate_qr(self, request, pk=None):
        table = services.regenerate_qr(self.get_object())
        return Response(TableSerializer(table).data)

    @extend_schema(responses={(200, "image/png"): OpenApiTypes.BINARY}, summary="QR de la table (PNG)")
    def qr_png(self, request, pk=None):
        table = self.get_object()
        response = HttpResponse(printing.qr_png(table.qr_url), content_type="image/png")
        response["Content-Disposition"] = f'inline; filename="table-{table.number}-qr.png"'
        return response

    @extend_schema(
        parameters=[OpenApiParameter("zone", int, description="Seulement les tables de cette zone"),
                    OpenApiParameter("number", int, description="Seulement cette table (chevalet à réimprimer)")],
        responses={(200, "application/pdf"): OpenApiTypes.BINARY},
        summary="Planche de chevalets A5 des tables actives (PDF)",
    )
    def qr_sheet(self, request):
        tables = self.filter_queryset(self.get_queryset()).filter(is_active=True)
        if not tables:
            return Response({"detail": "Aucune table active à imprimer."}, status=status.HTTP_404_NOT_FOUND)
        response = HttpResponse(printing.qr_sheet(tables), content_type="application/pdf")
        response["Content-Disposition"] = 'inline; filename="chevalets-qr.pdf"'
        return response
