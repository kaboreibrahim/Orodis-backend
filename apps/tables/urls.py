from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import TableViewSet, ZoneViewSet

router = SimpleRouter()
router.register("zones", ZoneViewSet, basename="manage-zone")
router.register("tables", TableViewSet, basename="manage-table")

# Fichiers sans barre finale (/qr.png, /qr-sheet.pdf), déclarés avant le routeur
# pour que « qr-sheet.pdf » ne soit pas pris pour l'identifiant d'une table.
manage_urlpatterns = [
    path("tables/qr-sheet.pdf", TableViewSet.as_view({"get": "qr_sheet"}), name="manage-table-qr-sheet"),
    path("tables/<int:pk>/qr.png", TableViewSet.as_view({"get": "qr_png"}), name="manage-table-qr-png"),
    *router.urls,
]
