from django.urls import path

from .views import LoginView, LogoutView, MeView, RefreshView

urlpatterns = [
    path("token/", LoginView.as_view(), name="auth-token"),
    path("token/refresh/", RefreshView.as_view(), name="auth-token-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
]
