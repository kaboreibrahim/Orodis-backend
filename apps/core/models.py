from django.core.exceptions import ValidationError
from django.db import models

DAYS = ("lun", "mar", "mer", "jeu", "ven", "sam", "dim")


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("créé le", auto_now_add=True)
    updated_at = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        abstract = True


def default_opening_hours():
    # Provisoire : horaires réels à confirmer avec le client
    return {day: [["11:00", "23:00"]] for day in DAYS}


class RestaurantSettings(TimeStampedModel):
    """Singleton : une seule ligne, toujours pk=1. Utiliser RestaurantSettings.load()."""

    name = models.CharField("nom", max_length=120, default="Les Délices d'Orodis")
    phone = models.CharField("téléphone", max_length=20, blank=True)
    whatsapp = models.CharField("WhatsApp", max_length=20, blank=True)
    email = models.EmailField("e-mail", blank=True)
    address = models.TextField("adresse", blank=True)
    maps_url = models.URLField("lien Google Maps", max_length=500, blank=True)
    opening_hours = models.JSONField(
        "horaires d'ouverture",
        default=default_opening_hours,
        help_text='Ex. {"lun": [["11:00", "15:00"], ["18:00", "23:00"]]}. Jour absent ou liste vide = fermé.',
    )

    reservation_slot_minutes = models.PositiveSmallIntegerField("durée d'un créneau (min)", default=30)
    reservation_max_party = models.PositiveSmallIntegerField(
        "taille maximale d'un groupe", default=12, help_text="Au-delà, le client est renvoyé vers le traiteur."
    )
    reservation_covers_per_slot = models.PositiveSmallIntegerField("couverts maximum par créneau", default=40)

    rccm = models.CharField("RCCM", max_length=50, blank=True)
    ncc = models.CharField("NCC", max_length=50, blank=True)
    vat_rate = models.DecimalField("taux de TVA (%)", max_digits=5, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "réglages du restaurant"
        verbose_name_plural = "réglages du restaurant"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Les réglages du restaurant ne peuvent pas être supprimés.")

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def clean(self):
        hours = self.opening_hours
        if not isinstance(hours, dict):
            raise ValidationError({"opening_hours": "Format attendu : un objet par jour."})
        for day, ranges in hours.items():
            if day not in DAYS:
                raise ValidationError({"opening_hours": f"Jour inconnu : « {day} ». Jours valides : {', '.join(DAYS)}."})
            for r in ranges:
                if not (isinstance(r, list) and len(r) == 2 and all(_is_hhmm(t) for t in r)):
                    raise ValidationError({"opening_hours": f"Plage invalide pour {day} : {r}. Format : [\"HH:MM\", \"HH:MM\"]."})
                if r[0] >= r[1]:
                    raise ValidationError({"opening_hours": f"Pour {day}, l'ouverture doit précéder la fermeture : {r}."})


def _is_hhmm(value):
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return False
    h, m = value[:2], value[3:]
    return h.isdigit() and m.isdigit() and int(h) < 24 and int(m) < 60
