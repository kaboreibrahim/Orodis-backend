from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.catering.urls import manage_urlpatterns as catering_manage
from apps.catering.urls import public_urlpatterns as catering_public
from apps.core.views import HealthCheckView, PublicSettingsView
from apps.reservations.urls import manage_urlpatterns as reservations_manage
from apps.reservations.urls import public_urlpatterns as reservations_public

api_v1 = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("settings/", PublicSettingsView.as_view(), name="settings"),
    path("menu/", include("apps.menu.urls")),
    path("reservations/", include(reservations_public)),
    path("manage/", include(reservations_manage)),
    path("catering/", include(catering_public)),
    path("manage/", include(catering_manage)),
]

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/v1/", include(api_v1)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    # Photos des plats servies par Django (volume /app/media), aussi en production
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
