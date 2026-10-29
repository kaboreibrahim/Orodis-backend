from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Reservation(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        CONFIRMED = "confirmed", "Confirmée"
        REFUSED = "refused", "Refusée"
        CANCELLED = "cancelled", "Annulée"
        NO_SHOW = "no_show", "Non venu"
        COMPLETED = "completed", "Terminée"

    class Source(models.TextChoices):
        SITE = "site", "Site"
        PHONE = "phone", "Téléphone"
        WALK_IN = "walk_in", "Sur place"

    reference = models.CharField("référence", max_length=20, unique=True, editable=False)
    date = models.DateField("date")
    time = models.TimeField("heure")
    party_size = models.PositiveSmallIntegerField("personnes")
    name = models.CharField("nom", max_length=100)
    phone = models.CharField("téléphone", max_length=20, help_text="Format +225XXXXXXXXXX.")
    note = models.TextField("note", blank=True)
    status = models.CharField("statut", max_length=20, choices=Status.choices, default=Status.PENDING)
    table = models.ForeignKey(
        "tables.Table", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reservations", verbose_name="table",
    )
    source = models.CharField("origine", max_length=20, choices=Source.choices, default=Source.SITE)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="traitée par",
    )
    handled_at = models.DateTimeField("traitée le", null=True, blank=True)
    refusal_reason = models.CharField("motif du refus", max_length=255, blank=True)

    class Meta:
        ordering = ["date", "time"]
        indexes = [models.Index(fields=["date", "status"])]
        verbose_name = "réservation"
        verbose_name_plural = "réservations"

    def __str__(self):
        return f"{self.reference} — {self.name} ({self.party_size} p.)"


# Statuts qui occupent des couverts sur un créneau
ACTIVE_STATUSES = [Reservation.Status.PENDING, Reservation.Status.CONFIRMED]
