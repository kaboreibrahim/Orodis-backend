from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

table_urlpatterns = [
    path("sessions/", views.OpenSessionView.as_view(), name="table-session-open"),
    path("session/", views.SessionStateView.as_view(), name="table-session"),
    path("orders/", views.TableOrderCreateView.as_view(), name="table-order-create"),
    path("orders/<int:number>/", views.TableOrderDetailView.as_view(), name="table-order"),
    path("requests/", views.TableRequestView.as_view(), name="table-request"),
    path("receipts/<int:number>/", views.TableReceiptView.as_view(), name="table-receipt"),
    path("receipts/<int:number>.pdf", views.TableReceiptPdfView.as_view(), name="table-receipt-pdf"),
    path("events/", views.TableEventsView.as_view(), name="table-events"),
]

router = SimpleRouter()
router.register("orders", views.StaffOrderViewSet, basename="manage-order")
router.register("requests", views.StaffRequestViewSet, basename="manage-request")
router.register("sessions", views.StaffSessionViewSet, basename="manage-session")
manage_urlpatterns = [
    path("receipts/<int:number>/", views.StaffReceiptView.as_view(), name="manage-receipt"),
    path("receipts/<int:number>.pdf", views.StaffReceiptPdfView.as_view(), name="manage-receipt-pdf"),
    path("events/", views.StaffEventsView.as_view(), name="manage-events"),
    *router.urls,
]
