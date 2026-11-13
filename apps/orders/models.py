import secrets

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


def new_session_token():
    return secrets.token_urlsafe(24)  # 32 caractères


class TableSession(TimeStampedModel):
    """Un repas à une table : regroupe les commandes jusqu'à l'addition. Une seule session ouverte par table."""

    class Status(models.TextChoices):
        OPEN = "open", "Ouverte"
        BILL_REQUESTED = "bill_requested", "Addition demandée"
        CLOSED = "closed", "Fermée"

    table = models.ForeignKey("tables.Table", on_delete=models.PROTECT, related_name="sessions", verbose_name="table")
    token = models.CharField("jeton", max_length=64, unique=True, default=new_session_token, editable=False)
    status = models.CharField("statut", max_length=20, choices=Status.choices, default=Status.OPEN)
    last_activity_at = models.DateTimeField("dernière activité", auto_now_add=True)
    closed_at = models.DateTimeField("fermée le", null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="fermée par",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "session de table"
        verbose_name_plural = "sessions de table"
        constraints = [
            models.UniqueConstraint(fields=["table"], condition=~Q(status="closed"), name="une_session_ouverte_par_table"),
        ]

    def __str__(self):
        return f"{self.table} · {self.get_status_display().lower()}"

    @property
    def is_closed(self):
        return self.status == self.Status.CLOSED


class Order(TimeStampedModel):
    class Channel(models.TextChoices):
        TABLE = "table", "À table (QR)"
        COUNTER = "counter", "Comptoir"

    class Status(models.TextChoices):
        RECEIVED = "received", "Reçue"
        PREPARING = "preparing", "En préparation"
        READY = "ready", "Prête"
        SERVED = "served", "Servie"
        CANCELLED = "cancelled", "Annulée"

    class PaymentTiming(models.TextChoices):
        NOW = "now", "Maintenant"
        END = "end", "À la fin du repas"

    class PaymentMethod(models.TextChoices):
        WAVE = "wave", "Wave"
        ORANGE_MONEY = "orange_money", "Orange Money"
        MTN_MOMO = "mtn_momo", "MTN MoMo"
        CASH = "cash", "Espèces"

    number = models.PositiveIntegerField("numéro", unique=True, editable=False)  # séquence PostgreSQL
    session = models.ForeignKey(
        TableSession, on_delete=models.PROTECT, null=True, blank=True, related_name="orders",
        verbose_name="session", help_text="Vide pour une saisie au comptoir.",
    )
    channel = models.CharField("canal", max_length=10, choices=Channel.choices, default=Channel.TABLE)
    status = models.CharField("statut", max_length=12, choices=Status.choices, default=Status.RECEIVED)
    payment_timing = models.CharField("paiement", max_length=5, choices=PaymentTiming.choices, default=PaymentTiming.END)
    payment_method = models.CharField(
        "moyen souhaité", max_length=15, choices=PaymentMethod.choices, blank=True,
        help_text="Choisi par le client ; la caisse confirme à l'encaissement.",
    )
    total = models.PositiveIntegerField("total (FCFA)", default=0)
    note = models.CharField("note pour la cuisine", max_length=300, blank=True)
    eta_minutes = models.PositiveSmallIntegerField("temps estimé (min)", default=15)
    accepted_at = models.DateTimeField("en préparation le", null=True, blank=True)
    ready_at = models.DateTimeField("prête le", null=True, blank=True)
    served_at = models.DateTimeField("servie le", null=True, blank=True)
    cancelled_at = models.DateTimeField("annulée le", null=True, blank=True)
    cancel_reason = models.CharField("motif d'annulation", max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="saisie par", help_text="Vide quand le client commande lui-même.",
    )
    status_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="dernier changement par",
    )
    receipt = models.ForeignKey(
        "Receipt", on_delete=models.PROTECT, null=True, blank=True, related_name="orders",
        verbose_name="reçu", help_text="Vide tant que la commande n'est pas payée.",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "commande"
        verbose_name_plural = "commandes"
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self):
        return f"Commande n° {self.number}"

    @property
    def is_paid(self):
        return self.receipt_id is not None


class OrderItem(TimeStampedModel):
    """Une ligne ; nom et prix figés au moment de la commande."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items", verbose_name="commande")
    dish = models.ForeignKey("menu.Dish", on_delete=models.PROTECT, related_name="+", verbose_name="plat")
    dish_name = models.CharField("plat", max_length=120)
    unit_price = models.PositiveIntegerField("prix du plat (FCFA)")
    quantity = models.PositiveSmallIntegerField("quantité")
    options_label = models.CharField("options", max_length=255, blank=True, help_text="Ex. Attiéké · piment doux.")
    options_price = models.PositiveIntegerField("suppléments (FCFA)", default=0, help_text="Par exemplaire.")
    note = models.CharField("précision pour la cuisine", max_length=200, blank=True)
    line_total = models.PositiveIntegerField("total de la ligne (FCFA)")

    class Meta:
        ordering = ["id"]
        verbose_name = "ligne de commande"
        verbose_name_plural = "lignes de commande"

    def __str__(self):
        return f"{self.quantity} × {self.dish_name}"


class OrderItemOption(TimeStampedModel):
    item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name="options", verbose_name="ligne")
    option = models.ForeignKey(
        "menu.Option", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="option",
    )
    name = models.CharField("option", max_length=80)
    price_delta = models.PositiveIntegerField("supplément (FCFA)", default=0)

    class Meta:
        ordering = ["id"]
        verbose_name = "option choisie"
        verbose_name_plural = "options choisies"

    def __str__(self):
        return self.name


class ServiceRequest(TimeStampedModel):
    """« Appeler un serveur » et « Demander l'addition »."""

    class Kind(models.TextChoices):
        WAITER = "waiter", "Appel serveur"
        BILL = "bill", "Addition"

    class Status(models.TextChoices):
        OPEN = "open", "En attente"
        DONE = "done", "Traitée"

    session = models.ForeignKey(TableSession, on_delete=models.CASCADE, related_name="requests", verbose_name="session")
    kind = models.CharField("type", max_length=10, choices=Kind.choices)
    status = models.CharField("statut", max_length=10, choices=Status.choices, default=Status.OPEN)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="traitée par",
    )
    handled_at = models.DateTimeField("traitée le", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "demande de la table"
        verbose_name_plural = "demandes des tables"
        constraints = [
            models.UniqueConstraint(fields=["session", "kind"], condition=Q(status="open"), name="une_demande_ouverte_par_type"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.session.table}"


class Receipt(TimeStampedModel):
    """Reçu d'un paiement : une commande payée tout de suite, toute l'addition d'une table, ou une partie."""

    number = models.PositiveIntegerField("numéro", unique=True, editable=False)  # séquence PostgreSQL
    session = models.ForeignKey(
        TableSession, on_delete=models.PROTECT, null=True, blank=True, related_name="receipts",
        verbose_name="session", help_text="Vide pour une commande au comptoir.",
    )
    total = models.PositiveIntegerField("total (FCFA)")
    method = models.CharField("moyen de paiement", max_length=15, choices=Order.PaymentMethod.choices)
    provider = models.CharField("fournisseur", max_length=20, default="manual")
    transaction_ref = models.CharField("référence de transaction", max_length=80, blank=True)
    paid_at = models.DateTimeField("payé le")
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="encaissé par",
    )

    class Meta:
        ordering = ["-paid_at"]
        verbose_name = "reçu"
        verbose_name_plural = "reçus"

    def __str__(self):
        return self.reference

    @property
    def reference(self):
        return f"R-{self.number:06d}"


class Event(TimeStampedModel):
    """Journal temps réel, relu par les écrans toutes les 3 à 5 s (pas de WebSocket chez LWS).
    Une ligne par destinataire ; purgé chaque nuit par la commande purge_events."""

    class Audience(models.TextChoices):
        STAFF = "staff", "Personnel"
        KITCHEN = "kitchen", "Cuisine"
        TABLES = "tables", "Toutes les tables"
        SESSION = "session", "Une table"

    audience = models.CharField("destinataires", max_length=10, choices=Audience.choices)
    session = models.ForeignKey(TableSession, on_delete=models.CASCADE, null=True, blank=True,
                                related_name="+", verbose_name="session")
    kind = models.CharField("événement", max_length=40)
    data = models.JSONField("contenu", default=dict)

    class Meta:
        ordering = ["id"]
        verbose_name = "événement"
        verbose_name_plural = "événements"
        indexes = [models.Index(fields=["audience", "id"])]
