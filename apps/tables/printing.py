"""QR des tables : image PNG et planche de chevalets A5 à imprimer (maquette docs/maquettes/phase3/Chevalet.dc.html).

La planche est dessinée en vectoriel avec ReportLab : une page A5 par table. Les mesures reprennent celles de la
maquette (559 × 794 px), converties en points. Polices PDF standard : Times pour les titres (proche de Fraunces),
Helvetica pour le reste.
"""

from io import BytesIO
from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A5
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

LOGO = Path(__file__).parent / "assets" / "logo-blanc.png"

# Couleurs de la charte (mêmes valeurs que app/globals.css du site)
BORDEAUX = HexColor("#810C1B")
JAUNE = HexColor("#EBE320")
CREME = HexColor("#FBF5EE")
ENCRE = HexColor("#241014")
TEXTE_DOUX = HexColor("#6B5458")
TEXTE_PALE = HexColor("#4A3A3E")
BORDURE = HexColor("#E2CFC6")
PAYMENTS = [("Wave", "#1DC8F2"), ("Orange Money", "#FF7900"), ("MTN MoMo", "#FFCB05"), ("Espèces", "#2E7D32")]
STEPS = [("Scannez", "avec l'appareil photo"), ("Choisissez", "sur la carte"), ("Savourez", "on vous sert")]

W, H = A5
S = W / 559  # 1 px de la maquette en points


def X(px):
    return px * S


def Y(px_from_top):
    """Ordonnée ReportLab (origine en bas) d'une position mesurée depuis le haut de la maquette."""
    return H - px_from_top * S


def qr_matrix(url):
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=0)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.get_matrix()


def qr_png(url, box_size=12):
    """QR seul, en PNG, avec la marge blanche réglementaire de 4 modules."""
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=box_size, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    buffer = BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def qr_sheet(tables):
    """Planche PDF : un chevalet A5 par table, dans l'ordre reçu."""
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A5)
    canvas.setTitle("Chevalets QR · Les Délices d'Orodis")
    canvas.setAuthor("Les Délices d'Orodis")
    logo = ImageReader(str(LOGO))
    for table in tables:
        _draw_tent_card(canvas, table, logo)
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def _draw_tent_card(c, table, logo):
    # Fond crème, bandeau bordeaux et vague soulignée de jaune
    c.setFillColor(CREME)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setFillColor(BORDEAUX)
    c.rect(0, Y(190), W, X(190), stroke=0, fill=1)
    wave = c.beginPath()
    wave.moveTo(X(0), Y(150 + 22))
    wave.curveTo(X(160), Y(150 + 46), X(380), Y(150), X(559), Y(150 + 26))
    wave.lineTo(X(559), Y(191))
    wave.lineTo(X(0), Y(191))
    wave.close()
    c.setFillColor(CREME)
    c.drawPath(wave, stroke=0, fill=1)
    line = c.beginPath()
    line.moveTo(X(0), Y(150 + 22))
    line.curveTo(X(160), Y(150 + 46), X(380), Y(150), X(559), Y(150 + 26))
    c.setStrokeColor(JAUNE)
    c.setLineWidth(X(4))
    c.drawPath(line, stroke=1, fill=0)

    # Logo blanc centré dans le bandeau
    logo_w, logo_h = logo.getSize()
    height = X(110)
    width = height * logo_w / logo_h
    c.drawImage(logo, (W - width) / 2, Y(34 + 110), width, height, mask="auto")

    # « Scannez pour commander »
    size = X(34)
    first, second = "Scannez ", "pour commander"
    w1 = c.stringWidth(first, "Times-Bold", size)
    w2 = c.stringWidth(second, "Times-BoldItalic", size)
    x = (W - w1 - w2) / 2
    c.setFillColor(ENCRE)
    c.setFont("Times-Bold", size)
    c.drawString(x, Y(238), first)
    c.setFillColor(BORDEAUX)
    c.setFont("Times-BoldItalic", size)
    c.drawString(x + w1, Y(238), second)

    # Carte blanche bordée de bordeaux, avec le QR en vectoriel
    card = 262
    card_x = (559 - card) / 2
    c.setFillColor(white)
    c.setStrokeColor(BORDEAUX)
    c.setLineWidth(X(3))
    c.roundRect(X(card_x), Y(258 + card), X(card), X(card), X(22), stroke=1, fill=1)
    # QR un peu plus petit que la maquette (204 au lieu de 220 px) : environ 3 modules de blanc avant la bordure,
    # pour que les téléphones le lisent du premier coup.
    _draw_qr(c, table.qr_url, X(card_x + 29), Y(258 + 29 + 204), X(204))

    # « TABLE 5 »
    label, number = "TABLE", str(table.number)
    label_size, number_size = X(16), X(72)
    spacing = label_size * 0.2
    label_w = sum(c.stringWidth(ch, "Helvetica-Bold", label_size) for ch in label) + spacing * (len(label) - 1)
    number_w = c.stringWidth(number, "Times-Bold", number_size)
    gap = X(12)
    x = (W - label_w - gap - number_w) / 2
    baseline = Y(590)
    # L'espacement des lettres reste dans l'état graphique : on l'isole pour ne pas étirer les textes suivants.
    c.saveState()
    c.setFillColor(TEXTE_DOUX)
    text = c.beginText(x, baseline)
    text.setFont("Helvetica-Bold", label_size)
    text.setCharSpace(spacing)
    text.textOut(label)
    c.drawText(text)
    c.restoreState()
    c.setFillColor(BORDEAUX)
    c.setFont("Times-Bold", number_size)
    c.drawString(x + label_w + gap, baseline, number)

    # Les 3 étapes
    column = (559 - 96) / 3
    for i, (title, sub) in enumerate(STEPS):
        cx = X(48 + column * i + column / 2)
        c.setFillColor(ENCRE)
        c.circle(cx, Y(632), X(20), stroke=0, fill=1)
        c.setFillColor(JAUNE)
        c.setFont("Times-Bold", X(18))
        c.drawCentredString(cx, Y(638), str(i + 1))
        c.setFillColor(ENCRE)
        c.setFont("Helvetica-Bold", X(14))
        c.drawCentredString(cx, Y(674), title)
        c.setFillColor(TEXTE_PALE)
        c.setFont("Helvetica", X(12))
        c.drawCentredString(cx, Y(692), sub)

    # Moyens de paiement, en pastilles
    font_size = X(12.5)
    pills = [(name, HexColor(color), X(10 + 9 + 6 + 10) + c.stringWidth(name, "Helvetica-Bold", font_size)) for name, color in PAYMENTS]
    total = sum(w for _, _, w in pills) + X(8) * (len(pills) - 1)
    x = (W - total) / 2
    top, height = 712, 28
    for name, color, width in pills:
        c.setFillColor(white)
        c.setStrokeColor(BORDURE)
        c.setLineWidth(X(1))
        c.roundRect(x, Y(top + height), width, X(height), X(height / 2), stroke=1, fill=1)
        c.setFillColor(color)
        c.circle(x + X(10 + 4.5), Y(top + height / 2), X(4.5), stroke=0, fill=1)
        c.setFillColor(ENCRE)
        c.setFont("Helvetica-Bold", font_size)
        c.drawString(x + X(10 + 9 + 6), Y(top + height / 2 + 4.5), name)
        x += width + X(8)

    c.setFillColor(TEXTE_PALE)
    c.setFont("Helvetica", X(12.5))
    c.drawCentredString(W / 2, Y(764), "Pas de téléphone ? Un serveur prend votre commande.")


def _draw_qr(c, url, x, y, size):
    """QR en rectangles noirs (net à toute taille d'impression), une bande par suite de modules sombres."""
    matrix = qr_matrix(url)
    count = len(matrix)
    module = size / count
    overlap = 0.3  # chaque bande déborde un peu sur la suivante : pas de filet blanc entre deux rangées
    c.setFillColor(ENCRE)
    for row, cells in enumerate(matrix):
        col = 0
        while col < count:
            if not cells[col]:
                col += 1
                continue
            start = col
            while col < count and cells[col]:
                col += 1
            extra = overlap if row < count - 1 else 0
            c.rect(x + start * module, y + size - (row + 1) * module - extra, (col - start) * module, module + extra, stroke=0, fill=1)
