from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel
from apps.core.utils import PhotoPath, is_new_upload, to_webp, unique_slug, validate_image_size


class SluggedModel(TimeStampedModel):
    """Nom + slug généré automatiquement + ordre d'affichage + actif."""

    name = models.CharField("nom", max_length=120)
    slug = models.SlugField("slug", max_length=60, unique=True, blank=True)
    position = models.PositiveSmallIntegerField("ordre", default=0)

    class Meta:
        abstract = True
        ordering = ["position", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)

        photo = getattr(self, "photo", None)
        old_photo = None
        if photo is not None and is_new_upload(photo):
            if self.pk:
                old_photo = type(self).objects.filter(pk=self.pk).values_list("photo", flat=True).first()
            to_webp(photo)

        super().save(*args, **kwargs)

        # Le nouveau fichier a un autre nom : on supprime l'ancien pour ne pas remplir le volume
        if old_photo and old_photo != photo.name:
            photo.storage.delete(old_photo)


class Category(SluggedModel):
    icon = models.CharField("icône", max_length=50, blank=True, help_text="Emoji ou nom d'icône utilisé par le site.")
    is_active = models.BooleanField("active", default=True)

    class Meta(SluggedModel.Meta):
        verbose_name = "catégorie"
        verbose_name_plural = "catégories"


class SubCategory(SluggedModel):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="subcategories", verbose_name="catégorie")
    photo = models.ImageField(
        "photo", upload_to=PhotoPath("menu/subcategories"), max_length=255, blank=True,
        validators=[validate_image_size],
    )
    is_active = models.BooleanField("active", default=True)

    class Meta(SluggedModel.Meta):
        verbose_name = "sous-catégorie"
        verbose_name_plural = "sous-catégories"


class Dish(SluggedModel):
    subcategory = models.ForeignKey(
        SubCategory, on_delete=models.PROTECT, related_name="dishes", verbose_name="sous-catégorie"
    )
    description = models.TextField("description", blank=True)
    price = models.PositiveIntegerField("prix (FCFA)")
    photo = models.ImageField(
        "photo", upload_to=PhotoPath("menu/dishes"), max_length=255, blank=True,
        validators=[validate_image_size],
    )
    is_available = models.BooleanField("disponible", default=True, help_text="Décocher pour une rupture de stock.")
    is_featured = models.BooleanField("mis en avant", default=False, help_text="Affiché sur la page d'accueil.")
    prep_minutes = models.PositiveSmallIntegerField("temps de préparation (min)", default=15)

    class Meta(SluggedModel.Meta):
        verbose_name = "plat"
        verbose_name_plural = "plats"


class OptionGroup(TimeStampedModel):
    dish = models.ForeignKey(Dish, on_delete=models.CASCADE, related_name="option_groups", verbose_name="plat")
    name = models.CharField("nom", max_length=80, help_text="Ex. Accompagnement, Piment.")
    min_choices = models.PositiveSmallIntegerField("choix minimum", default=0, help_text="0 = facultatif.")
    max_choices = models.PositiveSmallIntegerField("choix maximum", default=1)
    position = models.PositiveSmallIntegerField("ordre", default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "groupe d'options"
        verbose_name_plural = "groupes d'options"

    def __str__(self):
        return f"{self.dish} — {self.name}"

    def clean(self):
        if self.max_choices < 1:
            raise ValidationError({"max_choices": "Le maximum doit être au moins 1."})
        if self.min_choices > self.max_choices:
            raise ValidationError({"min_choices": "Le minimum ne peut pas dépasser le maximum."})


class Option(TimeStampedModel):
    group = models.ForeignKey(OptionGroup, on_delete=models.CASCADE, related_name="options", verbose_name="groupe")
    name = models.CharField("nom", max_length=80, help_text="Ex. Foutou, Attiéké.")
    price_delta = models.PositiveIntegerField("supplément (FCFA)", default=0)
    is_default = models.BooleanField("choisi par défaut", default=False)
    is_available = models.BooleanField("disponible", default=True)
    position = models.PositiveSmallIntegerField("ordre", default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "option"
        verbose_name_plural = "options"

    def __str__(self):
        return self.name
