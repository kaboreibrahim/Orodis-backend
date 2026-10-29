from .models import CateringFormula, QuoteRequest


def active_formulas():
    return CateringFormula.objects.filter(is_active=True)


def staff_quotes():
    return QuoteRequest.objects.select_related("formula")
