from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel
from apps.core.utils import unique_slug


class CateringFormula(TimeStampedModel):
    name = models.CharField("nom", max_length=80)
    slug = models.SlugField("slug", max_length=60, unique=True, blank=True)
    description = models.TextField("description", blank=True)
    price_from = models.PositiveIntegerField(
        "à partir de (FCFA / personne)", null=True, blank=True, help_text="Vide = « sur devis »."
    )
    items = models.JSONField("contenu", default=list, blank=True)
    is_highlighted = models.BooleanField("mise en avant", default=False)
    position = models.PositiveSmallIntegerField("ordre", default=0)
    is_active = models.BooleanField("active", default=True)

    class Meta:
        ordering = ["position", "name"]
        verbose_name = "formule traiteur"
        verbose_name_plural = "formules traiteur"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)

    def clean(self):
        if not isinstance(self.items, list) or not all(isinstance(i, str) and i.strip() for i in self.items):
            raise ValidationError({"items": "Une liste de lignes de texte non vides est attendue."})


class QuoteRequest(TimeStampedModel):
    class EventType(models.TextChoices):
        MARIAGE = "mariage", "Mariage"
        ANNIVERSAIRE = "anniversaire", "Anniversaire"
        BAPTEME = "bapteme", "Baptême"
        COCKTAIL = "cocktail", "Cocktail"
        SEMINAIRE = "seminaire", "Séminaire"
        BUFFET = "buffet", "Buffet"
        SOIREE_DINATOIRE = "soiree_dinatoire", "Soirée dînatoire"
        DINER_GALA = "diner_gala", "Dîner de gala"

    class PlaceType(models.TextChoices):
        RESTAURANT = "restaurant", "Au restaurant"
        DOMICILE = "domicile", "À domicile"
        AUTRE = "autre", "Autre lieu"

    class Status(models.TextChoices):
        NEW = "new", "Nouvelle"
        CONTACTED = "contacted", "Client contacté"
        QUOTE_SENT = "quote_sent", "Devis envoyé"
        WON = "won", "Gagnée"
        LOST = "lost", "Perdue"

    reference = models.CharField("référence", max_length=20, unique=True, editable=False)
    event_type = models.CharField("type d'événement", max_length=30, choices=EventType.choices)
    event_date = models.DateField("date de l'événement")
    guests = models.PositiveIntegerField("invités")
    place_type = models.CharField("lieu", max_length=20, choices=PlaceType.choices)
    place_detail = models.CharField("commune ou salle", max_length=150, blank=True)
    formula = models.ForeignKey(
        CateringFormula, on_delete=models.PROTECT, null=True, blank=True,
        related_name="quotes", verbose_name="formule", help_text="Vide = indécis.",
    )
    name = models.CharField("nom", max_length=100)
    whatsapp = models.CharField("WhatsApp", max_length=20, help_text="Format +225XXXXXXXXXX.")
    email = models.EmailField("e-mail", blank=True)
    message = models.TextField("message", blank=True)
    status = models.CharField("statut", max_length=20, choices=Status.choices, default=Status.NEW)
    internal_note = models.TextField("note interne", blank=True, help_text="Visible du personnel seulement.")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status"])]
        verbose_name = "demande de devis"
        verbose_name_plural = "demandes de devis"

    def __str__(self):
        return f"{self.reference} — {self.get_event_type_display()} ({self.guests} invités)"
