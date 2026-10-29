import uuid

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Zone(TimeStampedModel):
    name = models.CharField("nom", max_length=50, unique=True, help_text="Ex. Salle, Terrasse.")
    position = models.PositiveSmallIntegerField("ordre", default=0)

    class Meta:
        ordering = ["position", "name"]
        verbose_name = "zone"
        verbose_name_plural = "zones"

    def __str__(self):
        return self.name


class Table(TimeStampedModel):
    number = models.PositiveSmallIntegerField("numéro", unique=True)
    zone = models.ForeignKey(Zone, on_delete=models.PROTECT, related_name="tables", verbose_name="zone")
    seats = models.PositiveSmallIntegerField("places", default=4)
    is_active = models.BooleanField("active", default=True)
    qr_token = models.UUIDField("jeton QR", default=uuid.uuid4, unique=True, editable=False)
    qr_version = models.PositiveSmallIntegerField("version du QR", default=1, editable=False)

    class Meta:
        ordering = ["number"]
        verbose_name = "table"
        verbose_name_plural = "tables"

    def __str__(self):
        return f"Table {self.number}"

    @property
    def qr_url(self):
        """Adresse encodée dans le QR du chevalet."""
        return f"{settings.PUBLIC_SITE_URL}/t/{self.qr_token}"
