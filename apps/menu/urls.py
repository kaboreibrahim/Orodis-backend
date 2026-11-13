from django.urls import path

from .views import DishAvailabilityView, DishDetailView, FeaturedDishesView, MenuView, StaffDishListView

urlpatterns = [
    path("", MenuView.as_view(), name="menu"),
    path("featured/", FeaturedDishesView.as_view(), name="menu-featured"),
    path("dishes/<slug:slug>/", DishDetailView.as_view(), name="menu-dish"),
]

manage_urlpatterns = [
    path("dishes/", StaffDishListView.as_view(), name="manage-dishes"),
    path("dishes/<int:pk>/availability/", DishAvailabilityView.as_view(), name="manage-dish-availability"),
]
