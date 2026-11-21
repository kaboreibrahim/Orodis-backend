"""Rapports PDF du gérant (écran « Vue d'ensemble », bouton « Télécharger un rapport »).

- Rapport d'activité : les chiffres du tableau de bord pour une période (jour, 7 jours, 30 jours, dates libres).
- Clôture de caisse : la fiche de fin de service d'une journée (encaissé par moyen, reçus, annulations, signatures).
- Liste des ventes : chaque reçu de la période et les plats qu'il contient.

Même charte que le reçu A4 (printing.py). Mise en page ReportLab « platypus » : les tableaux longs
se poursuivent sur les pages suivantes avec leur en-tête répété."""

import datetime as dt
from io import BytesIO

from django.db.models import Count, Prefetch, Sum
from django.utils import timezone
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core.models import RestaurantSettings

from . import selectors
from .models import Order, OrderItem, Receipt
from .printing import BORDEAUX, CREME, ENCRE, FILET, JAUNE, LOGO, MONTHS, NBSP, ROSE, TEXTE_DOUX, VERT, fcfa

SABLE = HexColor("#F5ECE4")
RETARD = HexColor("#B3261E")
DAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
SALES_LIMIT = 3000  # reçus au plus dans la liste des ventes ; au-delà, le rapport le signale

W, H = A4
MARGIN = 16 * mm
WIDTH = W - 2 * MARGIN

BODY = ParagraphStyle("corps", fontName="Helvetica", fontSize=9.5, leading=13, textColor=ENCRE)
SMALL = ParagraphStyle("petit", parent=BODY, fontSize=8.5, leading=11, textColor=TEXTE_DOUX)
H1 = ParagraphStyle("titre", fontName="Times-Bold", fontSize=24, leading=28, textColor=BORDEAUX)
H2 = ParagraphStyle("section", fontName="Times-Bold", fontSize=14, leading=18, textColor=ENCRE, spaceBefore=14, spaceAfter=6)
CELL = ParagraphStyle("cellule", parent=BODY, fontSize=9, leading=11.5)
CELL_RIGHT = ParagraphStyle("cellule-droite", parent=CELL, alignment=TA_RIGHT)
KPI_LABEL = ParagraphStyle("kpi-libelle", parent=BODY, fontSize=8.5, leading=11, textColor=TEXTE_DOUX)
KPI_VALUE = ParagraphStyle("kpi-valeur", fontName="Times-Bold", fontSize=17, leading=21, textColor=ENCRE)
KPI_NOTE = ParagraphStyle("kpi-note", parent=SMALL, fontSize=8, leading=10)


# --- Mise en forme ----------------------------------------------------------------------------

def day_label(day):
    """« samedi 21 novembre 2026 »."""
    return f"{DAYS_FR[day.weekday()]} {day.day} {MONTHS[day.month - 1]} {day.year}"


def period_label(first, last):
    if first == last:
        return day_label(first)
    same_year = first.year == last.year
    start = f"{first.day} {MONTHS[first.month - 1]}" + ("" if same_year else f" {first.year}")
    return f"du {start} au {last.day} {MONTHS[last.month - 1]} {last.year}"


def evolution(now, before):
    """« +12 % » / « −8 % » par rapport à la période précédente ; « — » sans base de comparaison."""
    if not before:
        return "—"
    percent = round((now - before) * 100 / before)
    return f"{'+' if percent >= 0 else '−'}{abs(percent)}{NBSP}%"


def compared(now, before, versus):
    return f"{evolution(now, before)} vs {versus}" if before else f"rien à comparer ({versus})"


def local(moment, pattern="%d/%m/%Y %H:%M"):
    return timezone.localtime(moment).strftime(pattern)


def esc(value):
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def P(value, style=CELL):
    return Paragraph(esc(value), style)


def table(rows, widths, header=True, align_right=(), total_row=False, zebra=True):
    """Tableau aux couleurs du reçu : en-tête encre, lignes alternées crème, montants alignés à droite."""
    data = [[cell if not isinstance(cell, str) else P(cell, CELL_RIGHT if i in align_right else CELL)
             for i, cell in enumerate(row)] for row in rows]
    if header:
        data[0] = [Paragraph(f"<b>{esc(cell)}</b>", ParagraphStyle(
            f"entete-{i}", parent=CELL, textColor=white, fontSize=8.5, alignment=TA_RIGHT if i in align_right else TA_LEFT))
            for i, cell in enumerate(rows[0])]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, FILET),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), ENCRE), ("LINEBELOW", (0, 0), (-1, 0), 0, ENCRE)]
    if zebra:
        for r in range(1 if header else 0, len(data), 2):
            style.append(("BACKGROUND", (0, r), (-1, r), CREME))
    if total_row:
        style += [("BACKGROUND", (0, -1), (-1, -1), ROSE), ("LINEABOVE", (0, -1), (-1, -1), 1, BORDEAUX)]
    t.setStyle(TableStyle(style))
    return t


def kpis(cards):
    """Rangée d'indicateurs : [(libellé, valeur, note)] ; la première carte est en bordeaux."""
    cells = []
    for i, (label, value, note) in enumerate(cards):
        color = white if i == 0 else ENCRE
        soft = HexColor("#E9DCD5") if i == 0 else TEXTE_DOUX
        cells.append([
            Paragraph(esc(label), ParagraphStyle(f"kl{i}", parent=KPI_LABEL, textColor=soft)),
            Paragraph(esc(value), ParagraphStyle(f"kv{i}", parent=KPI_VALUE, textColor=color)),
            Paragraph(esc(note), ParagraphStyle(f"kn{i}", parent=KPI_NOTE, textColor=soft)),
        ])
    gap = 6
    width = (WIDTH - gap * (len(cards) - 1)) / len(cards)
    row, widths = [], []
    for i, cell in enumerate(cells):
        if i:
            row.append("")
            widths.append(gap)
        row.append(cell)
        widths.append(width)
    t = Table([row], colWidths=widths)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
             ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]
    for i in range(len(cells)):
        col = i * 2
        style += [("BACKGROUND", (col, 0), (col, 0), BORDEAUX if i == 0 else CREME),
                  ("BOX", (col, 0), (col, 0), 0.5, BORDEAUX if i == 0 else FILET)]
    t.setStyle(TableStyle(style))
    return t


def bar_rows(rows, label_width=42 * mm, value_width=34 * mm, color=BORDEAUX):
    """Petit histogramme horizontal en tableau : [(libellé, valeur, texte de la valeur)]."""
    peak = max((value for _, value, _ in rows), default=0) or 1
    bar_width = WIDTH - label_width - value_width
    data = []
    for label, value, shown in rows:
        bar = Table([[""]], colWidths=[max(0.5, bar_width * 0.96 * value / peak)], rowHeights=[7])
        bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), color if value else FILET)]))
        data.append([P(label), bar, P(shown, CELL_RIGHT)])
    t = Table(data, colWidths=[label_width, bar_width, value_width])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5), ("LEFTPADDING", (0, 0), (-1, -1), 4),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("ALIGN", (1, 0), (1, -1), "LEFT")]))
    return t


# --- Document --------------------------------------------------------------------------------

def _document(title, subtitle, story, author=""):
    """Assemble le PDF : bandeau bordeaux et jaune, logo, titre et période, pied de page numéroté."""
    rs = RestaurantSettings.load()
    generated = timezone.localtime()
    buffer = BytesIO()
    logo = ImageReader(str(LOGO))
    logo_w, logo_h = logo.getSize()

    def first_page(c, doc):
        _bands(c)
        height = 26 * mm
        c.drawImage(logo, W - MARGIN - height * logo_w / logo_h, H - 14 * mm - height, height * logo_w / logo_h, height, mask="auto")
        _footer(c, doc)

    def later_pages(c, doc):
        _bands(c)
        c.setFont("Times-Bold", 11)
        c.setFillColor(BORDEAUX)
        c.drawString(MARGIN, H - 12 * mm, f"{title} · {subtitle}")
        _footer(c, doc)

    def _footer(c, doc):
        c.setStrokeColor(FILET)
        c.setLineWidth(0.5)
        c.line(MARGIN, 14 * mm, W - MARGIN, 14 * mm)
        c.setFont("Helvetica", 7.5)
        c.setFillColor(TEXTE_DOUX)
        who = f" par {author}" if author else ""
        c.drawString(MARGIN, 9.5 * mm, f"{rs.name} · édité le {generated:%d/%m/%Y à %H:%M}{who} · montants en francs CFA")
        c.drawRightString(W - MARGIN, 9.5 * mm, f"Page {doc.page}")

    head = [Paragraph(esc(rs.name).upper(), ParagraphStyle("etab", parent=SMALL, fontName="Helvetica-Bold", textColor=TEXTE_DOUX,
                                                            fontSize=8.5)),
            Spacer(1, 3), Paragraph(esc(title), H1), Spacer(1, 2),
            Paragraph(esc(subtitle[0].upper() + subtitle[1:]), ParagraphStyle("periode", parent=BODY, fontSize=11, textColor=TEXTE_DOUX)),
            Spacer(1, 14)]
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=18 * mm, bottomMargin=20 * mm,
                            title=f"{title} · {subtitle}", author=rs.name)
    doc.build(head + story, onFirstPage=first_page, onLaterPages=later_pages)
    return buffer.getvalue()


def _bands(c):
    c.setFillColor(BORDEAUX)
    c.rect(0, H - 4 * mm, W, 4 * mm, stroke=0, fill=1)
    c.setFillColor(JAUNE)
    c.rect(0, H - 5.2 * mm, W, 1.2 * mm, stroke=0, fill=1)


def _empty(text):
    return Paragraph(esc(text), ParagraphStyle("vide", parent=BODY, textColor=TEXTE_DOUX, backColor=SABLE, borderPadding=8,
                                               spaceBefore=4, spaceAfter=6))


def _bounds(first, last):
    start = selectors._day_start(first)
    return start, selectors._day_start(last) + dt.timedelta(days=1)


# --- Rapport d'activité ------------------------------------------------------------------------

def summary_pdf(first, last, author=""):
    data = selectors.dashboard("custom", start=first, end=last, today=max(last, timezone.localdate()))
    cur, prev = data["current"], data["previous"]
    days = data["days"]
    versus = "veille" if days == 1 else f"{days} jours précédents"
    story = [kpis([
        ("Chiffre d'affaires encaissé", fcfa(cur["revenue"]), compared(cur["revenue"], prev["revenue"], versus)),
        ("Commandes", str(cur["orders_count"]), compared(cur["orders_count"], prev["orders_count"], versus)),
        ("Ticket moyen", fcfa(cur["average_ticket"]), f"{cur['receipts_count']} reçu{'s' if cur['receipts_count'] > 1 else ''}"),
        ("Annulations", str(cur["cancelled_count"]), f"{prev['cancelled_count']} sur la période précédente"),
    ])]

    story.append(Paragraph("Moyens de paiement", H2))
    if data["by_method"]:
        rows = [["Moyen", "Paiements", "Montant", "Part"]]
        for m in data["by_method"]:
            rows.append([m["label"], str(m["count"]), fcfa(m["total"]), f"{round(m['total'] * 100 / (cur['revenue'] or 1))}{NBSP}%"])
        rows.append(["Total", str(cur["receipts_count"]), fcfa(cur["revenue"]), f"100{NBSP}%"])
        story.append(table(rows, [WIDTH * 0.43, WIDTH * 0.17, WIDTH * 0.25, WIDTH * 0.15], align_right=(1, 2, 3), total_row=True))
    else:
        story.append(_empty("Aucun encaissement sur la période."))

    story.append(Paragraph("Ventes par catégorie", H2))
    if data["by_category"]:
        rows = [["Catégorie", "Articles", "Montant commandé", "Part"]]
        rows += [[c["name"], str(c["quantity"]), fcfa(c["revenue"]), f"{c['share']:g}{NBSP}%".replace(".", ",")] for c in data["by_category"]]
        story.append(table(rows, [WIDTH * 0.43, WIDTH * 0.17, WIDTH * 0.25, WIDTH * 0.15], align_right=(1, 2, 3)))
    else:
        story.append(_empty("Aucune commande sur la période."))

    start, end = _bounds(first, last)
    top = list(OrderItem.objects.filter(order__created_at__gte=start, order__created_at__lt=end)
               .exclude(order__status=Order.Status.CANCELLED)
               .values("dish_name").annotate(quantity=Sum("quantity"), revenue=Sum("line_total"))
               .order_by("-quantity", "-revenue", "dish_name")[:10])
    story.append(Paragraph("Plats les plus commandés", H2))
    if top:
        rows = [["#", "Plat", "Quantité", "Montant"]]
        rows += [[str(i), d["dish_name"], str(d["quantity"]), fcfa(d["revenue"])] for i, d in enumerate(top, 1)]
        story.append(table(rows, [WIDTH * 0.07, WIDTH * 0.53, WIDTH * 0.15, WIDTH * 0.25], align_right=(2, 3)))
    else:
        story.append(_empty("Aucune commande sur la période."))

    hours = [h for h in data["by_hour"] if h["orders_count"]]
    if hours:
        first_hour, last_hour = hours[0]["hour"], hours[-1]["hour"]
        rows = [(f"{h['hour']:02d}h – {h['hour'] + 1:02d}h", h["orders_count"],
                 f"{h['orders_count']} cde{'s' if h['orders_count'] > 1 else ''} · {fcfa(h['amount'])}")
                for h in data["by_hour"][first_hour:last_hour + 1]]
        busiest = max(hours, key=lambda h: h["orders_count"])
        story.append(KeepTogether([
            Paragraph("Affluence par heure", H2),
            Paragraph(esc(f"Heure la plus chargée : {busiest['hour']:02d}h – {busiest['hour'] + 1:02d}h "
                          f"({busiest['orders_count']} commande{'s' if busiest['orders_count'] > 1 else ''})."), SMALL),
            Spacer(1, 4),
            bar_rows(rows, color=HexColor("#E0782E")),
        ]))

    unit = "Semaine du" if data["trend_unit"] == "week" else "Jour"
    trend = [t for t in data["trend"] if first <= t["date"] <= last or data["trend_unit"] == "week"]
    if len(trend) > 1:
        rows = [["Semaine du" if unit == "Semaine du" else "Jour", "Commandes", "Encaissé"]]
        for t in trend:
            label = f"{t['date']:%d/%m/%Y}" if unit == "Semaine du" else f"{DAYS_FR[t['date'].weekday()][:3]}. {t['date']:%d/%m/%Y}"
            rows.append([label, str(t["orders_count"]), fcfa(t["revenue"])])
        rows.append(["Total", str(sum(t["orders_count"] for t in trend)), fcfa(sum(t["revenue"] for t in trend))])
        story.append(Paragraph("Recettes " + ("par semaine" if unit == "Semaine du" else "jour par jour"), H2))
        story.append(table(rows, [WIDTH * 0.5, WIDTH * 0.2, WIDTH * 0.3], align_right=(1, 2), total_row=True))

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "Encaissé : reçus émis sur la période (date du paiement). Commandes, catégories, plats et affluence : "
        "commandes passées sur la période (date de la commande), annulations exclues.", SMALL))
    return _document("Rapport d'activité", period_label(first, last), story, author)


# --- Clôture de caisse --------------------------------------------------------------------------

def closing_pdf(day, author=""):
    start, end = _bounds(day, day)
    receipts = list(Receipt.objects.filter(paid_at__gte=start, paid_at__lt=end)
                    .select_related("session__table", "cashier").annotate(orders_count=Count("orders")).order_by("paid_at"))
    labels = dict(Order.PaymentMethod.choices)
    totals = {value: [0, 0] for value in labels}
    for r in receipts:
        totals[r.method][0] += 1
        totals[r.method][1] += r.total
    revenue = sum(r.total for r in receipts)
    cash = totals.get("cash", [0, 0])[1]
    orders = Order.objects.filter(created_at__gte=start, created_at__lt=end)
    cancelled = list(orders.filter(status=Order.Status.CANCELLED).select_related("session__table").order_by("created_at"))
    unpaid = list(orders.filter(receipt__isnull=True).exclude(status=Order.Status.CANCELLED)
                  .select_related("session__table").order_by("created_at"))

    story = [kpis([
        ("Total encaissé", fcfa(revenue), f"{len(receipts)} reçu{'s' if len(receipts) > 1 else ''}"),
        ("Espèces en caisse", fcfa(cash), f"{totals.get('cash', [0])[0]} paiement{'s' if totals.get('cash', [0])[0] > 1 else ''}"),
        ("Mobile Money", fcfa(revenue - cash), "Wave, Orange Money, MTN"),
        ("Reste à encaisser", fcfa(sum(o.total for o in unpaid)), f"{len(unpaid)} commande{'s' if len(unpaid) > 1 else ''} du jour"),
    ])]

    story.append(Paragraph("Encaissé par moyen de paiement", H2))
    rows = [["Moyen", "Paiements", "Montant"]]
    rows += [[labels[value], str(count), fcfa(amount)] for value, (count, amount) in totals.items()]
    rows.append(["Total", str(len(receipts)), fcfa(revenue)])
    story.append(table(rows, [WIDTH * 0.5, WIDTH * 0.2, WIDTH * 0.3], align_right=(1, 2), total_row=True))

    story.append(Paragraph("Reçus de la journée", H2))
    if receipts:
        rows = [["Heure", "Reçu", "Table", "Moyen", "Référence", "Caissier", "Montant"]]
        for r in receipts:
            cashier = (r.cashier.get_full_name() or r.cashier.username) if r.cashier else "—"
            rows.append([local(r.paid_at, "%H:%M"), r.reference, f"Table {r.session.table.number}" if r.session else "Comptoir",
                         labels.get(r.method, r.method), r.transaction_ref or "—", cashier, fcfa(r.total)])
        rows.append(["", "", "", "", "", "Total", fcfa(revenue)])
        story.append(table(rows, [WIDTH * w for w in (0.08, 0.12, 0.12, 0.16, 0.2, 0.15, 0.17)], align_right=(6,), total_row=True))
    else:
        story.append(_empty("Aucun encaissement ce jour-là."))

    story.append(Paragraph("Commandes annulées", H2))
    if cancelled:
        rows = [["Heure", "Commande", "Table", "Motif", "Montant"]]
        rows += [[local(o.created_at, "%H:%M"), f"n° {o.number}", f"Table {o.session.table.number}" if o.session else "Comptoir",
                  o.cancel_reason or "—", fcfa(o.total)] for o in cancelled]
        story.append(table(rows, [WIDTH * w for w in (0.09, 0.13, 0.13, 0.45, 0.2)], align_right=(4,)))
    else:
        story.append(_empty("Aucune annulation."))

    if unpaid:
        story.append(Paragraph("Commandes du jour non encaissées", H2))
        rows = [["Heure", "Commande", "Table", "Statut", "Montant"]]
        rows += [[local(o.created_at, "%H:%M"), f"n° {o.number}", f"Table {o.session.table.number}" if o.session else "Comptoir",
                  o.get_status_display(), fcfa(o.total)] for o in unpaid]
        story.append(table(rows, [WIDTH * w for w in (0.09, 0.15, 0.15, 0.36, 0.25)], align_right=(4,)))

    # Comptage et signatures : à remplir à la main à la fermeture
    story.append(KeepTogether([
        Paragraph("Comptage de la caisse", H2),
        table([["", "Montant"], ["Espèces attendues (selon les reçus)", fcfa(cash)], ["Espèces comptées", ""], ["Écart", ""]],
              [WIDTH * 0.6, WIDTH * 0.4], align_right=(1,), zebra=False),
        Spacer(1, 18),
        _signatures(),
    ]))
    return _document("Clôture de caisse", day_label(day), story, author)


def _signatures():
    box = ParagraphStyle("signature", parent=SMALL, textColor=TEXTE_DOUX)
    t = Table([[Paragraph("Caissier : nom et signature", box), "", Paragraph("Gérant : nom et signature", box)]],
              colWidths=[WIDTH * 0.47, WIDTH * 0.06, WIDTH * 0.47], rowHeights=[22 * mm])
    t.setStyle(TableStyle([("BOX", (0, 0), (0, 0), 0.6, FILET), ("BOX", (2, 0), (2, 0), 0.6, FILET),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6)]))
    return t


# --- Liste des ventes ------------------------------------------------------------------------------

def sales_pdf(first, last, author=""):
    start, end = _bounds(first, last)
    labels = dict(Order.PaymentMethod.choices)
    queryset = (Receipt.objects.filter(paid_at__gte=start, paid_at__lt=end).select_related("session__table", "cashier")
                .prefetch_related(Prefetch("orders", queryset=Order.objects.order_by("number").prefetch_related("items")))
                .order_by("paid_at"))
    count = queryset.count()
    receipts = list(queryset[:SALES_LIMIT])
    revenue = queryset.aggregate(total=Sum("total", default=0))["total"]
    articles = OrderItem.objects.filter(order__receipt__paid_at__gte=start, order__receipt__paid_at__lt=end).aggregate(
        n=Sum("quantity", default=0))["n"]

    story = [kpis([
        ("Total encaissé", fcfa(revenue), period_label(first, last)),
        ("Reçus", str(count), f"ticket moyen {fcfa(revenue // count) if count else '—'}"),
        ("Articles vendus", str(articles), "plats et boissons payés"),
    ]), Spacer(1, 12)]

    if not receipts:
        story.append(_empty("Aucun encaissement sur la période."))
        return _document("Liste des ventes", period_label(first, last), story, author)

    rows = [["Date", "Reçu · table", "Plat", "Qté", "Montant"]]
    shades = []
    for r in receipts:
        where = f"Table {r.session.table.number}" if r.session else "Comptoir"
        first_row = len(rows)
        items = [item for order in r.orders.all() for item in order.items.all()]
        for i, item in enumerate(items):
            name = item.dish_name + (f" ({item.options_label})" if item.options_label else "")
            rows.append([local(r.paid_at) if i == 0 else "", f"{r.reference} · {where}" if i == 0 else "",
                         name, str(item.quantity), fcfa(item.line_total)])
        method = labels.get(r.method, r.method) + (f" · {r.transaction_ref}" if r.transaction_ref else "")
        rows.append(["", "", Paragraph(f"<b>Total du reçu</b> · {esc(method)}", CELL), "", Paragraph(f"<b>{fcfa(r.total)}</b>", CELL_RIGHT)])
        shades.append((first_row, len(rows) - 1))
    rows.append(["", "", Paragraph("<b>Total de la période</b>", CELL), "", Paragraph(f"<b>{fcfa(revenue)}</b>", CELL_RIGHT)])

    t = table(rows, [WIDTH * w for w in (0.17, 0.22, 0.38, 0.07, 0.16)], align_right=(3, 4), total_row=True, zebra=False)
    extra = []
    for index, (top, bottom) in enumerate(shades):
        if index % 2:
            extra.append(("BACKGROUND", (0, top), (-1, bottom), CREME))
        extra.append(("LINEBELOW", (0, bottom), (-1, bottom), 0.8, TEXTE_DOUX))
    t.setStyle(TableStyle(extra))
    story.append(t)
    if count > SALES_LIMIT:
        story.append(Spacer(1, 6))
        story.append(Paragraph(esc(f"Seuls les {SALES_LIMIT} premiers reçus sur {count} sont détaillés : choisissez une période plus courte "
                                   "pour avoir tout le détail. Les totaux en tête portent sur toute la période."), SMALL))
    story.append(Spacer(1, 8))
    story.append(Paragraph(esc(f"{count} reçu{'s' if count > 1 else ''} · plats commandés avec leurs options · montants TTC."), SMALL))
    return _document("Liste des ventes", period_label(first, last), story, author)


def pdf_filename(kind, first, last):
    span = f"{first:%Y-%m-%d}" if first == last else f"{first:%Y-%m-%d}_au_{last:%Y-%m-%d}"
    return f"orodis-{kind}-{span}.pdf"


_ = (VERT, RETARD)  # couleurs gardées pour de futurs rapports
