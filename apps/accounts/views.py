from django.db.models import Case, IntegerField, Value, When
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.core.permissions import IsManager, IsStaffRole
from apps.core.throttling import ScopedRateThrottle

from . import services
from .models import User
from .serializers import (
    LogoutSerializer,
    MeSerializer,
    PasswordChangeSerializer,
    StaffCreateSerializer,
    StaffCredentialsSerializer,
    StaffMemberSerializer,
)


class LoginView(TokenObtainPairView):
    """Connexion du personnel : {username, password} → {access, refresh}. django-axes verrouille après 5 échecs."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class RefreshView(TokenRefreshView):
    """Nouveau jeton d'accès ; le jeton de rafraîchissement tourne et l'ancien part en liste noire."""


class LogoutView(APIView):
    # Le jeton de rafraîchissement suffit à prouver la session : la déconnexion marche même avec un accès expiré.
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(request=LogoutSerializer, responses={204: None}, summary="Déconnexion (jeton de rafraîchissement en liste noire)")
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError:
            return Response({"refresh": ["Jeton invalide ou expiré."]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsStaffRole]

    @extend_schema(responses=MeSerializer, summary="Membre du personnel connecté et son rôle")
    def get(self, request):
        return Response(MeSerializer(request.user).data)


class PasswordChangeView(APIView):
    """Le membre connecté change son mot de passe (obligatoire après un mot de passe provisoire)."""

    permission_classes = [IsStaffRole]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(request=PasswordChangeSerializer, responses=MeSerializer, summary="Changer mon mot de passe")
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        services.change_own_password(request.user, serializer.validated_data["new_password"])
        return Response(MeSerializer(request.user).data)


ROLE_ORDER = Case(*(When(role=value, then=Value(index)) for index, (value, _) in enumerate(User.Role.choices)),
                  output_field=IntegerField())


class StaffViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Comptes du personnel (gérant). Pas de suppression : un compte qui a servi reste dans l'historique
    des commandes et des reçus ; on le désactive."""

    permission_classes = [IsManager]
    pagination_class = None
    http_method_names = ["get", "post", "patch"]
    queryset = User.objects.annotate(role_order=ROLE_ORDER).order_by("-is_active", "role_order", "first_name", "username")

    def get_serializer_class(self):
        return StaffCreateSerializer if self.action == "create" else StaffMemberSerializer

    @extend_schema(request=StaffCreateSerializer, responses={201: StaffCredentialsSerializer}, summary="Créer un compte")
    def create(self, request, *args, **kwargs):
        serializer = StaffCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member, password = services.create_member(serializer.validated_data)
        member.temporary_password = password
        return Response(StaffCredentialsSerializer(member).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        serializer.instance = services.update_member(self.request.user, serializer.instance, serializer.validated_data)

    @extend_schema(request=None, responses=StaffCredentialsSerializer, summary="Donner un mot de passe provisoire")
    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        member = self.get_object()
        member.temporary_password = services.reset_password(request.user, member)
        return Response(StaffCredentialsSerializer(member).data)
