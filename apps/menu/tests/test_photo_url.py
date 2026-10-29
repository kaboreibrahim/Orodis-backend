import pytest
from django.test import override_settings
from rest_framework.test import APIRequestFactory

from apps.menu.models import Category, Dish, SubCategory
from apps.menu.serializers import DishSerializer

PUBLIC_MEDIA_URL = "https://api.delicesdorodis.ci/media/"


@pytest.mark.django_db
@override_settings(MEDIA_URL=PUBLIC_MEDIA_URL)
def test_photo_a_une_url_publique_meme_par_l_adresse_interne():
    sub = SubCategory.objects.create(name="Sauces", category=Category.objects.create(name="Plats"))
    dish = Dish.objects.create(name="Kedjenou", price=4500, subcategory=sub)
    dish.photo.name = "menu/dishes/kedjenou.webp"  # pas d'envoi de fichier : seule l'URL compte

    # Next.js appelle l'API par le réseau interne de Docker
    request = APIRequestFactory().get("/api/v1/menu/", HTTP_HOST="orodis-api:8000")
    data = DishSerializer(dish, context={"request": request}).data

    assert data["photo"] == "https://api.delicesdorodis.ci/media/menu/dishes/kedjenou.webp"
