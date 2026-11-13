from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.core.permissions import IsStaffRole
from apps.core.throttling import ScopedRateThrottle

from .serializers import LogoutSerializer, MeSerializer


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
