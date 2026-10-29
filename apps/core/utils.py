from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.deconstruct import deconstructible
from django.utils.text import slugify
from PIL import Image, ImageOps

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PX = 1200
WEBP_QUALITY = 80


def unique_slug(instance, value, field="slug"):
    """Slug sans accents, unique dans la table : kedjenou, kedjenou-2…"""
    base = slugify(value)[:50] or "element"
    slug, n = base, 2
    qs = type(instance)._default_manager.exclude(pk=instance.pk)
    while qs.filter(**{field: slug}).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


@deconstructible
class PhotoPath:
    """upload_to : menu/dishes/kedjenou.webp"""

    def __init__(self, folder):
        self.folder = folder

    def __call__(self, instance, filename):
        return f"{self.folder}/{instance.slug}.webp"


def validate_image_size(file):
    if file.size > MAX_UPLOAD_BYTES:
        raise ValidationError("L'image ne doit pas dépasser 5 Mo.")


def is_new_upload(field_file):
    """Vrai si le fichier vient d'être envoyé et n'est pas encore enregistré."""
    return bool(field_file) and not getattr(field_file, "_committed", True)


def to_webp(field_file, max_px=MAX_IMAGE_PX):
    """Remet la photo à l'endroit, la réduit à max_px sur son plus grand côté
    et la convertit en WebP (ce qui supprime les métadonnées EXIF, dont la position GPS)."""
    field_file.seek(0)
    img = ImageOps.exif_transpose(Image.open(field_file))
    img.thumbnail((max_px, max_px))
    if img.mode not in ("RGB", "RGBA"):
        transparent = img.mode in ("LA", "PA") or "transparency" in img.info
        img = img.convert("RGBA" if transparent else "RGB")

    buffer = BytesIO()
    img.save(buffer, format="WEBP", quality=WEBP_QUALITY, method=6)
    field_file.save("photo.webp", ContentFile(buffer.getvalue()), save=False)
