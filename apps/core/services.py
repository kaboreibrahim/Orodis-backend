import json
import logging
import urllib.request
from threading import Thread

from django.conf import settings
from django.db import connection, transaction

logger = logging.getLogger(__name__)

REVALIDATE_TIMEOUT = 3  # secondes


def notify_frontend_revalidate(tags):
    """Demande au site Next.js de revalider ces tags de cache, une fois la transaction validée.
    Les tags demandés pendant une même transaction partent en un seul POST, dans un thread démon :
    un site lent ou injoignable ne bloque jamais l'admin ni seed_menu.
    Ne fait rien si FRONTEND_REVALIDATE_URL est vide ; ne lève jamais d'erreur."""
    url = settings.FRONTEND_REVALIDATE_URL
    if not url:
        return
    batch = _pending_batch()
    if batch is not None:
        batch.add(tags)
        return
    batch = _RevalidateBatch(url)
    batch.add(tags)
    transaction.on_commit(batch)  # hors transaction : exécuté tout de suite


class _RevalidateBatch:
    """Tags à envoyer au commit de la transaction en cours, sans doublon, dans l'ordre d'arrivée."""

    def __init__(self, url):
        self.url, self.tags, self.sent = url, {}, False

    def add(self, tags):
        self.tags.update(dict.fromkeys(tags))

    def __call__(self):
        self.sent = True
        _start_post(self.url, list(self.tags))


def _pending_batch():
    """Lot déjà programmé pour la transaction en cours, ou None.
    Un rollback retire le lot de la file on_commit : la demande suivante en recrée un."""
    for _, func, _ in connection.run_on_commit:
        if isinstance(func, _RevalidateBatch) and not func.sent:
            return func
    return None


def _start_post(url, tags):
    Thread(target=_post_revalidate, args=(url, tags), daemon=True, name="revalidate-next").start()


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
