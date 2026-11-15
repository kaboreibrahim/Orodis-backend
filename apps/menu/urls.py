from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    DishAvailabilityView, DishDetailView, FeaturedDishesView, ManageCategoryViewSet, ManageDishViewSet,
    ManageMenuView, ManageReorderView, ManageSubCategoryViewSet, MenuView, StaffDishListView,
)

# Gestion de la carte par le gérant : /manage/menu/…
router = SimpleRouter()
router.register("menu/categories", ManageCategoryViewSet, basename="manage-menu-category")
router.register("menu/subcategories", ManageSubCategoryViewSet, basename="manage-menu-subcategory")
router.register("menu/dishes", ManageDishViewSet, basename="manage-menu-dish")

urlpatterns = [
    path("", MenuView.as_view(), name="menu"),
    path("featured/", FeaturedDishesView.as_view(), name="menu-featured"),
    path("dishes/<slug:slug>/", DishDetailView.as_view(), name="menu-dish"),
]

manage_urlpatterns = [
    path("dishes/", StaffDishListView.as_view(), name="manage-dishes"),
    path("dishes/<int:pk>/availability/", DishAvailabilityView.as_view(), name="manage-dish-availability"),
    path("menu/", ManageMenuView.as_view(), name="manage-menu"),
    path("menu/reorder/", ManageReorderView.as_view(), name="manage-menu-reorder"),
    *router.urls,
]
