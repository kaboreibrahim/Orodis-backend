from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasRole, IsStaffRole
from apps.tables.models import Table

from . import printing, selectors, services
from .authentication import HasTableSession, TableEventsThrottle, TableSessionAuthentication, TableSessionThrottle
from .models import Order, ServiceRequest, TableSession
from .serializers import (
    CancelOrderSerializer, EventSerializer, EventsSerializer, OpenSessionSerializer, OpenSessionSummarySerializer, PaySerializer, PlaceOrderSerializer,
    ReceiptSerializer, ServiceRequestInputSerializer, StaffReceiptSerializer, ServiceRequestSerializer, SessionOpenedSerializer,
    SessionStateSerializer, StaffOrderSerializer, StaffPlaceOrderSerializer, StaffServiceRequestSerializer,
    TableOrderSerializer,
)


def _receipt_or_404(number, session=None):
    found = selectors.receipt(number, session)
    if found is None:
        raise NotFound("Reçu introuvable.")
    return found


def _pdf_response(receipt):
    response = HttpResponse(printing.receipt_pdf(receipt), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="recu-{receipt.reference}.pdf"'
    return response


class TableView(APIView):
    """Routes du téléphone : en-tête X-Session-Token ; par session, 120 lectures et 30 écritures par minute."""

    authentication_classes = [TableSessionAuthentication]
    permission_classes = [HasTableSession]
    throttle_classes = [TableSessionThrottle]


class EventsMixin:
    """Polling toutes les 3 à 5 s. Sans ?after= (ouverture de l'écran), on ne renvoie que le curseur actuel :
    l'écran charge l'état complet par REST, puis relit les événements à partir de ce curseur."""

    def read_events(self, request, after):
        raise NotImplementedError

    @extend_schema(parameters=[OpenApiParameter("after", int, description="Curseur du dernier appel.")],
                   responses=EventsSerializer, summary="Événements depuis le curseur")
    def get(self, request):
        after = request.query_params.get("after", "")
        if not after.isdigit():
            return Response({"cursor": selectors.latest_event_id(), "events": []})
        events = self.read_events(request, int(after))
        return Response({"cursor": events[-1].id if events else int(after),
                         "events": EventSerializer(events, many=True).data})


class TableEventsView(EventsMixin, TableView):
    throttle_classes = [TableEventsThrottle]

    def read_events(self, request, after):
        return selectors.table_events(request.auth, after)


class OpenSessionView(TableView):
    permission_classes = [AllowAny]

    @extend_schema(request=OpenSessionSerializer, responses={200: SessionOpenedSerializer},
                   summary="Ouvrir ou reprendre la session de la table scannée")
    def post(self, request):
        serializer = OpenSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = services.open_session(serializer.validated_data["qr_token"])
        return Response(SessionOpenedSerializer(session).data)


class SessionStateView(TableView):
    @extend_schema(responses=SessionStateSerializer, summary="Session, commandes, demandes ouvertes et addition")
    def get(self, request):
        return Response(SessionStateSerializer(selectors.session_state(request.auth)).data)


class TableOrderCreateView(TableView):
    @extend_schema(request=PlaceOrderSerializer, responses={201: TableOrderSerializer}, summary="Envoyer une commande en cuisine")
    def post(self, request):
        serializer = PlaceOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = services.place_order(session=request.auth, **serializer.validated_data)
        order = selectors.table_order(request.auth, order.number)
        return Response(TableOrderSerializer(order).data, status=status.HTTP_201_CREATED)


class TableOrderDetailView(TableView):
    @extend_schema(responses=TableOrderSerializer, summary="Suivi d'une commande de cette table")
    def get(self, request, number):
        order = selectors.table_order(request.auth, number)
        if order is None:
            raise NotFound("Commande introuvable pour cette table.")
        return Response(TableOrderSerializer(order).data)


class TableRequestView(TableView):
    @extend_schema(request=ServiceRequestInputSerializer, responses={200: ServiceRequestSerializer, 201: ServiceRequestSerializer},
                   summary="Appeler un serveur ou demander l'addition")
    def post(self, request):
        serializer = ServiceRequestInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        req, created = services.request_service(request.auth, serializer.validated_data["kind"])
        return Response(ServiceRequestSerializer(req).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


# Téléphone : reçus de CETTE table seulement
class TableReceiptView(TableView):
    @extend_schema(responses=ReceiptSerializer, summary="Reçu de cette table")
    def get(self, request, number):
        return Response(ReceiptSerializer(_receipt_or_404(number, request.auth)).data)


class TableReceiptPdfView(TableView):
    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY}, summary="Reçu de cette table (PDF A4)")
    def get(self, request, number):
        return _pdf_response(_receipt_or_404(number, request.auth))


# --- Personnel ------------------------------------------------------------------------------

class StaffEventsView(EventsMixin, APIView):
    permission_classes = [IsStaffRole]

    def read_events(self, request, after):
        return selectors.staff_events(request.user, after)


class OrdersPagination(PageNumberPagination):
    page_size = 100  # une journée de service tient sur une page


class OrderFilter(filters.FilterSet):
    status = filters.CharFilter(method="noop", help_text="Un ou plusieurs statuts, séparés par des virgules.")
    channel = filters.ChoiceFilter(choices=Order.Channel.choices, method="noop")
    date = filters.DateFilter(method="noop", help_text="AAAA-MM-JJ, heure d'Abidjan.")
    table = filters.NumberFilter(method="noop", help_text="Numéro de table.")

    def noop(self, queryset, name, value):
        return queryset  # filtres appliqués par selectors.staff_orders ; déclarés ici pour être validés et documentés

    class Meta:
        model = Order
        fields = []


class StaffOrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Gestion, caisse et serveurs : toutes les commandes ; cuisine : commandes actives seulement.
    Les droits de chaque transition sont vérifiés par les services (advance, cancel)."""

    queryset = Order.objects.none()  # type du modèle pour le Swagger ; la vraie liste vient de get_queryset
    serializer_class = StaffOrderSerializer
    permission_classes = [IsStaffRole]
    pagination_class = OrdersPagination
    filterset_class = OrderFilter

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Order.objects.none()
        params = self.request.query_params
        form = OrderFilter(params)
        cleaned = form.form.cleaned_data if form.is_valid() else {}
        return selectors.staff_orders(self.request.user, status=params.get("status"), channel=cleaned.get("channel"),
                                      date=cleaned.get("date"), table=cleaned.get("table"))

    def get_permissions(self):
        if self.action == "create":
            return [HasRole("cashier", "manager")()]
        return super().get_permissions()

    @extend_schema(request=StaffPlaceOrderSerializer, responses={201: StaffOrderSerializer},
                   summary="Saisie au comptoir, ou pour une table sans téléphone")
    def create(self, request):
        serializer = StaffPlaceOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        table_number = data.pop("table_number")
        session = None
        if table_number is not None:
            table = Table.objects.filter(number=table_number, is_active=True).first()
            if table is None:
                return Response({"table_number": ["Table inconnue ou désactivée."]}, status=status.HTTP_400_BAD_REQUEST)
            session = services.session_for_table(table)
        order = services.place_order(session=session, created_by=request.user, **data)
        return Response(StaffOrderSerializer(self.get_queryset().get(pk=order.pk)).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=StaffOrderSerializer, summary="Étape suivante de la commande")
    @action(detail=True, methods=["post"])
    def advance(self, request, pk=None):
        order = services.advance(self.get_object(), request.user)
        return Response(StaffOrderSerializer(self.get_queryset().get(pk=order.pk)).data)

    @extend_schema(request=CancelOrderSerializer, responses=StaffOrderSerializer, summary="Annuler (gérant, caisse)")
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        serializer = CancelOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = services.cancel(self.get_object(), request.user, serializer.validated_data["reason"])
        return Response(StaffOrderSerializer(self.get_queryset().get(pk=order.pk)).data)

    @extend_schema(request=PaySerializer, responses={201: ReceiptSerializer}, summary="Encaisser une commande au comptoir")
    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        serializer = PaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        paid = services.pay_order(self.get_object(), data["method"], data["transaction_ref"], request.user)
        return Response(ReceiptSerializer(selectors.receipt(paid.number)).data, status=status.HTTP_201_CREATED)


class StaffRequestViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = StaffServiceRequestSerializer
    permission_classes = [HasRole("waiter", "cashier", "manager")]
    pagination_class = None
    filterset_fields = []

    def get_queryset(self):
        wanted = self.request.query_params.get("status", ServiceRequest.Status.OPEN)
        return selectors.staff_requests(None if wanted == "all" else wanted)

    @extend_schema(request=None, responses=StaffServiceRequestSerializer, summary="Demande traitée")
    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        req = get_object_or_404(ServiceRequest, pk=pk)
        req = services.complete_request(req, request.user)
        return Response(StaffServiceRequestSerializer(req).data)


class StaffSessionViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = TableSession.objects.none()
    serializer_class = OpenSessionSummarySerializer
    permission_classes = [HasRole("waiter", "cashier", "manager")]
    pagination_class = None
    filterset_fields = []

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TableSession.objects.none()
        wanted = self.request.query_params.get("status")
        return selectors.open_sessions(wanted if wanted in TableSession.Status.values else None)

    @extend_schema(request=PaySerializer, responses={201: ReceiptSerializer}, summary="Encaisser l'addition (caisse, gérant)")
    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        serializer = PaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = get_object_or_404(TableSession, pk=pk)
        paid = services.pay(session, cashier=request.user, **serializer.validated_data)
        return Response(ReceiptSerializer(selectors.receipt(paid.number)).data, status=status.HTTP_201_CREATED)


# Personnel : caisse et gérant
class StaffReceiptView(APIView):
    permission_classes = [HasRole("cashier", "manager")]

    @extend_schema(responses=StaffReceiptSerializer, summary="Reçu, avec les mentions légales du ticket 80 mm")
    def get(self, request, number):
        return Response(StaffReceiptSerializer(_receipt_or_404(number)).data)


class StaffReceiptPdfView(StaffReceiptView):
    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY}, summary="Reçu (PDF A4)")
    def get(self, request, number):
        return _pdf_response(_receipt_or_404(number))
