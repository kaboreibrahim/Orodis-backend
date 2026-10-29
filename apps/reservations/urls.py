from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import AvailabilityView, ReservationCreateView, ReservationManageViewSet

public_urlpatterns = [
    path("availability/", AvailabilityView.as_view(), name="reservation-availability"),
    path("", ReservationCreateView.as_view(), name="reservation-create"),
]

router = SimpleRouter()
router.register("reservations", ReservationManageViewSet, basename="manage-reservation")
manage_urlpatterns = router.urls
