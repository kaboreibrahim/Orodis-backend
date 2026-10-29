import json
import logging
import urllib.request

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

REVALIDATE_TIMEOUT = 3  # secondes


def notify_frontend_revalidate(tags):
    """Demande au site Next.js de revalider ces tags de cache, une fois la transaction validée.
    Ne fait rien si FRONTEND_REVALIDATE_URL est vide ; ne lève jamais d'erreur."""
    url = settings.FRONTEND_REVALIDATE_URL
    if not url:
        return
    tags = list(tags)
    transaction.on_commit(lambda: _post_revalidate(url, tags))


def _post_revalidate(url, tags):
    request = urllib.request.Request(
        url,
        data=json.dumps({"tags": tags}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "x-revalidate-secret": settings.REVALIDATE_SECRET},
    )
    try:
        with urllib.request.urlopen(request, timeout=REVALIDATE_TIMEOUT) as response:
            response.read()
    except Exception as exc:  # site injoignable, délai dépassé, réponse 4xx/5xx
        logger.warning("Revalidation Next.js impossible pour %s (%s) : %s", tags, url, exc)
