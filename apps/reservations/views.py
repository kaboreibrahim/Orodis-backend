from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasRole
from apps.core.throttling import ScopedRateThrottle

from . import selectors, services
from .serializers import (
    ActionResultSerializer, AvailabilityQuerySerializer, AvailabilitySerializer, ConfirmSerializer,
    RefuseSerializer, ReservationCreateSerializer, ReservationPublicSerializer, ReservationStaffSerializer,
    StaffReservationCreateSerializer,
)

CAN_READ = HasRole("waiter", "cashier", "manager")
CAN_MANAGE = HasRole("cashier", "manager")


# --- Public -------------------------------------------------------------------------------

class AvailabilityView(APIView):
    """Throttle anon par défaut (60/min, IP via core.throttling), pas de cache."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(parameters=[AvailabilityQuerySerializer], responses=AvailabilitySerializer,
                   summary="Créneaux d'un jour pour un nombre de personnes")
    def get(self, request):
        query = AvailabilityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = services.available_slots(query.validated_data["date"], query.validated_data["party"])
        return Response(AvailabilitySerializer(data).data)


class ReservationCreateView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "reservations"

    @extend_schema(request=ReservationCreateSerializer, responses={201: ReservationPublicSerializer},
                   summary="Demande de réservation (statut pending)")
    def post(self, request):
        serializer = ReservationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation = services.create_reservation(**serializer.validated_data)
        return Response(ReservationPublicSerializer(reservation).data, status=status.HTTP_201_CREATED)


# --- Personnel ----------------------------------------------------------------------------

class ReservationManageViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ReservationStaffSerializer
    filterset_fields = ["date", "status", "source"]

    def get_queryset(self):
        qs = selectors.staff_reservations()
        user = self.request.user
        if getattr(user, "role", None) == "waiter" and not user.is_superuser:
            qs = qs.filter(date=timezone.localdate())  # le serveur ne voit que le jour même
        return qs

    def get_permissions(self):
        return [CAN_READ()] if self.action in ("list", "retrieve") else [CAN_MANAGE()]

    def _result(self, reservation, whatsapp_url, status_code=status.HTTP_200_OK):
        data = {"reservation": ReservationStaffSerializer(reservation).data, "whatsapp_url": whatsapp_url}
        return Response(data, status=status_code)

    @extend_schema(request=StaffReservationCreateSerializer, responses={201: ActionResultSerializer},
                   summary="Saisie d'une réservation prise au téléphone ou sur place (confirmée)")
    def create(self, request):
        serializer = StaffReservationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation = services.create_reservation(**serializer.validated_data, created_by=request.user)
        return self._result(reservation, services.notify(reservation, "confirmed"), status.HTTP_201_CREATED)

    @extend_schema(request=ConfirmSerializer, responses=ActionResultSerializer)
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        body = ConfirmSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._result(*services.confirm_reservation(
            self.get_object(), request.user, table=body.validated_data.get("table")
        ))

    @extend_schema(request=RefuseSerializer, responses=ActionResultSerializer)
    @action(detail=True, methods=["post"])
    def refuse(self, request, pk=None):
        body = RefuseSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._result(*services.refuse_reservation(self.get_object(), request.user, body.validated_data["reason"]))

    @extend_schema(request=None, responses=ActionResultSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._result(*services.cancel_reservation(self.get_object(), request.user))

    @extend_schema(request=None, responses=ActionResultSerializer)
    @action(detail=True, methods=["post"], url_path="no-show")
    def no_show(self, request, pk=None):
        return self._result(*services.mark_no_show(self.get_object(), request.user))

    @extend_schema(request=None, responses=ActionResultSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return self._result(*services.complete_reservation(self.get_object(), request.user))
