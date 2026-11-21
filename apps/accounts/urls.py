from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    LoginView,
    LogoutView,
    MeView,
    PasswordChangeView,
    RefreshView,
    StaffViewSet,
)

urlpatterns = [
    path("token/", LoginView.as_view(), name="auth-token"),
    path("token/refresh/", RefreshView.as_view(), name="auth-token-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("password/", PasswordChangeView.as_view(), name="auth-password"),
]

# Comptes du personnel, pour le gérant : /manage/staff/…
router = SimpleRouter()
router.register("staff", StaffViewSet, basename="manage-staff")
manage_urlpatterns = router.urls
