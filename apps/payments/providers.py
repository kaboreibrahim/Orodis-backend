"""Fournisseurs de paiement (docs/phase3.md, section Paiement).
Phase 3 : un seul fournisseur, « manuel » — la caisse encaisse et confirme. Brancher un agrégateur Mobile Money
= ajouter une classe ici (initiate, verify, handle_webhook) sans toucher aux commandes."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.conf import settings


class PaymentStatus:
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"


@dataclass(frozen=True)
class PaymentInitiation:
    provider_ref: str
    redirect_url: str | None = None  # page de paiement de l'agrégateur ; None = rien à afficher au client


class PaymentProvider(ABC):
    code = ""

    @abstractmethod
    def initiate(self, receipt_draft) -> PaymentInitiation:
        """receipt_draft : {"total", "method", "transaction_ref", "orders"} avant création du reçu."""

    @abstractmethod
    def verify(self, provider_ref) -> str:
        """Statut du paiement : PaymentStatus.PAID, PENDING ou FAILED."""

    @abstractmethod
    def handle_webhook(self, request):
        """Notification signée de l'agrégateur ; renvoie (provider_ref, statut)."""


class ManualProvider(PaymentProvider):
    """La caisse a reçu l'argent (espèces, ou Mobile Money avec sa référence) : le paiement est acquis."""

    code = "manual"

    def initiate(self, receipt_draft):
        return PaymentInitiation(provider_ref=receipt_draft.get("transaction_ref", ""))

    def verify(self, provider_ref):
        return PaymentStatus.PAID

    def handle_webhook(self, request):
        raise NotImplementedError("Le paiement manuel n'a pas de webhook.")


PROVIDERS = {provider.code: provider for provider in (ManualProvider,)}


def get_provider(code=None):
    return PROVIDERS[code or settings.PAYMENT_PROVIDER]()
