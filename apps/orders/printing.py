"""Reçu PDF A4 (modèle RecuA4) : coordonnées et mentions légales depuis RestaurantSettings, « À compléter » sinon.
Mesures de la maquette (794 × 1123 px) converties en points ; Times pour les titres, Helvetica pour le reste.
Le ticket 80 mm est une page du site Next.js (/gestion/recus/[number]/ticket), sur les mêmes données."""

from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from apps.core.models import DAYS, RestaurantSettings

LOGO = Path(settings.BASE_DIR) / "apps" / "tables" / "assets" / "logo-couleur.png"

# Couleurs de la charte (mêmes valeurs que app/globals.css du site) et du modèle de reçu
BORDEAUX = HexColor("#810C1B")
JAUNE = HexColor("#EBE320")
ENCRE = HexColor("#1C1214")
TEXTE_DOUX = HexColor("#6B5458")
TEXTE_PALE = HexColor("#4A3A3E")
CREME = HexColor("#FBF5EE")
ROSE = HexColor("#F4E3E1")
FILET = HexColor("#D9C9C3")
VERT = HexColor("#1F7A45")

TO_FILL = "À compléter"
NBSP = " "
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]
METHODS = {
    "wave": "Wave (Mobile Money)",
    "orange_money": "Orange Money (Mobile Money)",
    "mtn_momo": "MTN MoMo (Mobile Money)",
    "cash": "Espèces",
}
DAY_LABELS = {"lun": "lundi", "mar": "mardi", "mer": "mercredi", "jeu": "jeudi",
              "ven": "vendredi", "sam": "samedi", "dim": "dimanche"}

W, H = A4
S = W / 794  # 1 px de la maquette en points
LEFT, RIGHT = 72, 722
ROW_H = 46
FOOTER_TOP = 975

# Lignes d'articles par page : sans le bloc paiement et totaux (CAP), et avec (LAST)
FIRST_CAP, FIRST_LAST = 10, 5
NEXT_CAP, NEXT_LAST = 16, 12


def X(px):
    return px * S


def Y(px_from_top):
    """Ordonnée ReportLab (origine en bas) d'une position mesurée depuis le haut de la maquette."""
    return H - px_from_top * S


# --- Mise en forme ----------------------------------------------------------------------------

def fcfa(amount, suffix="F"):
    """8000 → « 8 000 F » (espaces insécables)."""
    return f"{amount:,}".replace(",", NBSP) + f"{NBSP}{suffix}"


def long_date(moment):
    moment = timezone.localtime(moment)
    return f"{moment.day} {MONTHS[moment.month - 1]} {moment.year} · {moment:%H:%M}"


def short_date(moment):
    return f"{timezone.localtime(moment):%d/%m/%Y à %H:%M}"


def phone(raw):
    """« 0584603011 », « 2250584603011 », « +225 05… » → « +225 05 84 60 30 11 » ; sinon tel quel."""
    digits = "".join(ch for ch in raw or "" if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 13 and digits.startswith("225"):
        digits = digits[3:]
    if len(digits) != 10:
        return raw or ""
    # Espaces insécables : le numéro passe toujours entier à la ligne
    return "+225" + NBSP + NBSP.join(digits[i:i + 2] for i in range(0, 10, 2))


UNITS = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix",
         "onze", "douze", "treize", "quatorze", "quinze", "seize"]
TENS = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}


def _below_100(n, plural=True):
    if n < 17:
        return UNITS[n]
    if n < 20:
        return "dix-" + UNITS[n - 10]
    if n < 70:
        tens, unit = divmod(n, 10)
        if unit == 0:
            return TENS[tens]
        return f"{TENS[tens]} et un" if unit == 1 else f"{TENS[tens]}-{UNITS[unit]}"
    if n < 80:
        return "soixante et onze" if n == 71 else "soixante-" + _below_100(n - 60)
    if n == 80:
        return "quatre-vingts" if plural else "quatre-vingt"
    return "quatre-vingt-" + _below_100(n - 80)


def _below_1000(n, plural=True):
    """plural=False devant « mille » : « deux cent mille », « quatre-vingt mille »."""
    hundreds, rest = divmod(n, 100)
    words = []
    if hundreds:
        if hundreds == 1:
            words.append("cent")
        else:
            words.append(f"{UNITS[hundreds]} cent" + ("s" if rest == 0 and plural else ""))
    if rest or not hundreds:
        words.append(_below_100(rest, plural))
    return " ".join(words)


def amount_in_words(n):
    """8000 → « huit mille » ; 13500 → « treize mille cinq cents » (orthographe traditionnelle)."""
    if n == 0:
        return "zéro"
    millions, rest = divmod(n, 1_000_000)
    thousands, units = divmod(rest, 1000)
    words = []
    if millions:
        words.append("un million" if millions == 1 else f"{_below_1000(millions)} millions")
    if thousands:
        words.append("mille" if thousands == 1 else f"{_below_1000(thousands, plural=False)} mille")
    if units:
        words.append(_below_1000(units))
    return " ".join(words)


def opening_hours_line(rs):
    """« Ouvert tous les jours, 11:00 – 23:00 », « Ouvert 24h/24, 7j/7 » ou les jours regroupés."""
    def label(ranges):
        if not ranges:
            return "fermé"
        return ", ".join("24h/24" if (a, b) == ("00:00", "23:59") else f"{a} – {b}" for a, b in ranges)

    hours = rs.opening_hours or {}
    labels = [label(hours.get(day)) for day in DAYS]
    if len(set(labels)) == 1:
        return "Ouvert 24h/24, 7j/7" if labels[0] == "24h/24" else f"Ouvert tous les jours, {labels[0]}"
    groups = []
    for day, text in zip(DAYS, labels):
        if groups and groups[-1][2] == text:
            groups[-1][1] = day
        else:
            groups.append([day, day, text])
    parts = [
        f"{DAY_LABELS[a]} {text}" if a == b else f"du {DAY_LABELS[a]} au {DAY_LABELS[b]} {text}"
        for a, b, text in groups
    ]
    return "Horaires : " + " ; ".join(parts)


def ellipsize(c, text, font, size, width):
    if c.stringWidth(text, font, size) <= width:
        return text
    while text and c.stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def wrap(c, text, font, size, width):
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and c.stringWidth(candidate, font, size) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    return lines + ([current] if current else [])


def spaced(c, x, y, text, font, size, spacing, color):
    """Petit libellé en capitales espacées (ÉTABLISSEMENT, PAIEMENT…) ; l'espacement ne déborde pas."""
    c.saveState()
    c.setFillColor(color)
    t = c.beginText(x, y)
    t.setFont(font, size)
    t.setCharSpace(spacing)
    t.textOut(text)
    c.drawText(t)
    c.restoreState()


def text(c, x, y, value, font="Helvetica", size=14, color=ENCRE, align="left"):
    c.setFillColor(color)
    c.setFont(font, X(size))
    draw = {"left": c.drawString, "right": c.drawRightString, "center": c.drawCentredString}[align]
    draw(X(x), Y(y), value)


# --- Document -----------------------------------------------------------------------------------

def receipt_pdf(receipt):
    """Reçu en PDF ; plusieurs pages si l'addition est longue (en-tête du tableau répété)."""
    rs = RestaurantSettings.load()
    orders = list(receipt.orders.select_related("session__table").prefetch_related("items").order_by("number"))
    items = [item for order in orders for item in order.items.all()]
    pages = _paginate(items)

    buffer = BytesIO()
    c = Canvas(buffer, pagesize=A4)
    c.setTitle(f"Reçu {receipt.reference} · {rs.name}")
    c.setAuthor(rs.name)
    for index, page_items in enumerate(pages, 1):
        _bands(c)
        table_top = _header(c, receipt, rs, orders) if index == 1 else _short_header(c, receipt)
        bottom = _rows(c, page_items, table_top)
        if index == len(pages):
            _payment_and_totals(c, receipt, rs, bottom)
        _footer(c, rs, index, len(pages))
        c.showPage()
    c.save()
    return buffer.getvalue()


def _paginate(items):
    """Découpe les articles ; la dernière page garde la place du bloc paiement et totaux."""
    pages, start, first = [], 0, True
    while True:
        remaining = len(items) - start
        cap, last_cap = (FIRST_CAP, FIRST_LAST) if first else (NEXT_CAP, NEXT_LAST)
        if remaining <= last_cap:
            pages.append(items[start:])
            return pages
        take = min(cap, remaining - 1)  # au moins un article accompagne les totaux
        pages.append(items[start:start + take])
        start += take
        first = False


def _bands(c):
    c.setFillColor(BORDEAUX)
    c.rect(0, Y(10), W, X(10), stroke=0, fill=1)
    c.setFillColor(JAUNE)
    c.rect(0, Y(13), W, X(3), stroke=0, fill=1)


def _header(c, receipt, rs, orders):
    # Logo couleur à gauche
    logo = ImageReader(str(LOGO))
    logo_w, logo_h = logo.getSize()
    height = X(120)
    c.drawImage(logo, X(LEFT), Y(64 + 120), height * logo_w / logo_h, height, mask="auto")

    # « REÇU », numéro et date à droite
    text(c, RIGHT, 100, "REÇU", "Times-Bold", 40, BORDEAUX, "right")
    number_w = c.stringWidth(receipt.reference, "Helvetica-Bold", X(14))
    text(c, RIGHT, 132, receipt.reference, "Helvetica-Bold", 14, ENCRE, "right")
    c.setFont("Helvetica", X(14))
    c.drawRightString(X(RIGHT) - number_w, Y(132), "N° ")
    text(c, RIGHT, 152, long_date(receipt.paid_at), size=14, align="right")

    # Établissement
    spaced(c, X(LEFT), Y(224), "ÉTABLISSEMENT", "Helvetica-Bold", X(12), X(12) * 0.12, TEXTE_DOUX)
    text(c, LEFT, 252, rs.name, "Helvetica-Bold", 16)
    contact = " · ".join(filter(None, [
        f"Tél. {phone(rs.phone)}" if rs.phone else "",
        f"WhatsApp {phone(rs.whatsapp)}" if rs.whatsapp else "",
    ]))
    lines = ["Pâtisserie · Restauration · Service", rs.address or f"Adresse : {TO_FILL.lower()}", contact, rs.email]
    y = 274
    for line in filter(None, lines):
        for part in wrap(c, line.replace("\n", " "), "Helvetica", X(14), X(315)):
            text(c, LEFT, y, part, size=14)
            y += 21
    legal = f"RCCM {rs.rccm or TO_FILL} · N° compte contribuable {rs.ncc or TO_FILL}"
    for part in wrap(c, legal, "Helvetica", X(14), X(315)):
        text(c, LEFT, y + 4, part, size=14, color=TEXTE_PALE)
        y += 21

    # Encadré « COMMANDE »
    box_x, box_top, box_w, box_h = 409, 212, RIGHT - 409, 198
    c.setFillColor(CREME)
    c.roundRect(X(box_x), Y(box_top + box_h), X(box_w), X(box_h), X(12), stroke=0, fill=1)
    spaced(c, X(box_x + 18), Y(240), "COMMANDE", "Helvetica-Bold", X(12), X(12) * 0.12, TEXTE_DOUX)
    session = receipt.session
    cashier = (receipt.cashier.get_full_name() or receipt.cashier.username) if receipt.cashier else "—"
    rows = [
        ("N°", ", ".join(str(o.number) for o in orders), "Helvetica-Bold"),
        ("Service", f"Sur place · table {session.table.number}" if session else "Comptoir", "Helvetica"),
        ("Encaissé par", cashier, "Helvetica"),
    ]
    for i, (label, value, font) in enumerate(rows):
        y = 266 + i * 23
        text(c, box_x + 18, y, label, size=14, color=TEXTE_PALE)
        text(c, box_x + 120, y, ellipsize(c, value, font, X(14), X(box_w - 138)), font, 14)

    return 455


def _short_header(c, receipt):
    text(c, LEFT, 70, f"Reçu {receipt.reference} (suite)", "Times-Bold", 22, BORDEAUX)
    text(c, RIGHT, 70, long_date(receipt.paid_at), size=13, color=TEXTE_PALE, align="right")
    return 130


COLUMNS = [  # (titre, x, alignement, largeur max)
    ("DÉSIGNATION", LEFT, "left", 186),
    ("OPTIONS", 266, "left", 196),
    ("QTÉ", 504, "right", 40),
    ("PRIX UNIT.", 616, "right", 100),
    ("MONTANT", RIGHT, "right", 100),
]


def _rows(c, items, header_y):
    for title, x, align, _ in COLUMNS:
        width = c.stringWidth(title, "Helvetica-Bold", X(11)) + X(11) * 0.08 * (len(title) - 1)
        start = X(x) - width if align == "right" else X(x)
        spaced(c, start, Y(header_y), title, "Helvetica-Bold", X(11), X(11) * 0.08, ENCRE)
    c.setStrokeColor(ENCRE)
    c.setLineWidth(X(1.5))
    c.line(X(LEFT), Y(header_y + 15), X(RIGHT), Y(header_y + 15))

    top = header_y + 15
    c.setStrokeColor(FILET)
    c.setLineWidth(X(1))
    for i, item in enumerate(items):
        baseline = top + i * ROW_H + 28
        unit = item.unit_price + item.options_price
        cells = [
            (item.dish_name, "Helvetica-Bold", ENCRE),
            (item.options_label + (f" · {item.note}" if item.note else ""), "Helvetica", TEXTE_PALE),
            (str(item.quantity), "Helvetica", ENCRE),
            (fcfa(unit), "Helvetica", ENCRE),
            (fcfa(item.line_total), "Helvetica", ENCRE),
        ]
        for (value, font, color), (_, x, align, width) in zip(cells, COLUMNS):
            text(c, x, baseline, ellipsize(c, value, font, X(14), X(width)), font, 14, color, align)
        c.line(X(LEFT), Y(top + (i + 1) * ROW_H), X(RIGHT), Y(top + (i + 1) * ROW_H))
    return top + len(items) * ROW_H


def _payment_and_totals(c, receipt, rs, bottom):
    top = bottom + 32

    # Paiement, à gauche
    spaced(c, X(LEFT), Y(top + 10), "PAIEMENT", "Helvetica-Bold", X(12), X(12) * 0.12, TEXTE_DOUX)
    rows = [
        ("Moyen", METHODS.get(receipt.method, receipt.method)),
        ("Référence", receipt.transaction_ref or "—"),
        ("Date", short_date(receipt.paid_at)),
    ]
    for i, (label, value) in enumerate(rows):
        y = top + 38 + i * 23
        text(c, LEFT, y, label, size=14, color=TEXTE_PALE)
        text(c, LEFT + 81, y, ellipsize(c, value, "Helvetica", X(14), X(250)), size=14)

    # Tampon « PAYÉ », incliné
    c.saveState()
    c.translate(X(LEFT + 44), Y(top + 146))
    c.rotate(4)
    c.setStrokeColor(VERT)
    c.setLineWidth(X(2.5))
    c.roundRect(X(-44), X(-18), X(88), X(36), X(8), stroke=1, fill=0)
    c.setFillColor(VERT)
    c.setFont("Helvetica-Bold", X(18))
    t = c.beginText(X(-30), X(-6))
    t.setFont("Helvetica-Bold", X(18))
    t.setCharSpace(X(18) * 0.14)
    t.textOut("PAYÉ")
    c.drawText(t)
    c.restoreState()

    # Totaux, à droite
    left = 432
    vat = rs.vat_rate
    if vat:
        rate = float(vat)
        vat_label = f"TVA incluse ({f'{rate:g}'.replace('.', ',')}{NBSP}%)"
        vat_value = fcfa(round(receipt.total * rate / (100 + rate)))
    else:
        vat_label, vat_value = "TVA", TO_FILL
    lines = [("Sous-total", fcfa(receipt.total)), ("Service à table", "Inclus"), (vat_label, vat_value)]
    for i, (label, value) in enumerate(lines):
        y = top + 10 + i * 27
        text(c, left, y, label, size=14, color=TEXTE_PALE)
        text(c, RIGHT, y, value, size=14, align="right")

    box_top = top + 10 + 2 * 27 + 22
    c.setFillColor(ROSE)
    c.roundRect(X(left), Y(box_top + 62), X(RIGHT - left), X(62), X(12), stroke=0, fill=1)
    text(c, left + 16, box_top + 39, "Total TTC", "Times-Bold", 18)
    text(c, RIGHT - 16, box_top + 41, fcfa(receipt.total, "F CFA"), "Times-Bold", 26, BORDEAUX, "right")

    words = amount_in_words(receipt.total)
    sentence = f"Arrêté à la somme de {words} franc{'s' if receipt.total > 1 else ''} CFA."
    for i, part in enumerate(wrap(c, sentence, "Helvetica", X(13), X(RIGHT - left))):
        text(c, RIGHT, box_top + 88 + i * 18, part, size=13, color=TEXTE_PALE, align="right")


def _footer(c, rs, index, count):
    c.setStrokeColor(FILET)
    c.setLineWidth(X(1))
    c.line(X(LEFT), Y(FOOTER_TOP), X(RIGHT), Y(FOOTER_TOP))
    text(c, LEFT, FOOTER_TOP + 35, "Merci de votre visite !", "Times-BoldItalic", 20, BORDEAUX)
    first = f"{opening_hours_line(rs)} · sur place, à emporter, traiteur pour vos événements."
    for i, part in enumerate(wrap(c, first, "Helvetica", X(13), X(500))[:2]):
        text(c, LEFT, FOOTER_TOP + 62 + i * 20, part, size=13, color=TEXTE_PALE)
    text(c, LEFT, FOOTER_TOP + 102, "Montants exprimés en francs CFA, toutes taxes comprises.", size=13, color=TEXTE_PALE)
    site = urlparse(settings.PUBLIC_SITE_URL).netloc or settings.PUBLIC_SITE_URL
    text(c, RIGHT, FOOTER_TOP + 62, site, size=12, color=TEXTE_PALE, align="right")
    text(c, RIGHT, FOOTER_TOP + 82, f"Page {index} / {count}", size=12, color=TEXTE_PALE, align="right")
