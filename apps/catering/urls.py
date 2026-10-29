from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import FormulaListView, QuoteCreateView, QuoteManageViewSet

public_urlpatterns = [
    path("formulas/", FormulaListView.as_view(), name="catering-formulas"),
    path("quotes/", QuoteCreateView.as_view(), name="catering-quote-create"),
]

router = SimpleRouter()
router.register("quotes", QuoteManageViewSet, basename="manage-quote")
manage_urlpatterns = router.urls
