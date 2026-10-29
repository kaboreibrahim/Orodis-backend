from django.urls import path

from .views import DishDetailView, FeaturedDishesView, MenuView

urlpatterns = [
    path("", MenuView.as_view(), name="menu"),
    path("featured/", FeaturedDishesView.as_view(), name="menu-featured"),
    path("dishes/<slug:slug>/", DishDetailView.as_view(), name="menu-dish"),
]
