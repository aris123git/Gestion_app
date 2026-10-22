"""Factures « modèles fidèles » : Services (vagues) et Médical.

Le dessin d'origine des modèles (fonds PDF préparés par
``tools/build_invoice_templates.py``) sert de fond de page ; les vraies données
sont écrites par-dessus, aux positions et avec les polices (Lato, Montserrat)
des modèles. Les fonds et les polices sont dans ``app/assets/``.

Page finale : A4 portrait (les modèles font 216 × 303 mm ; la mise à l'échelle
vers 210 × 297 mm est de ~2 %, invisible).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

from app import config
from app.services import settings_service
from app.utils.helpers import format_amount, format_money, format_quantity

logger = logging.getLogger(__name__)

TPL_W, TPL_H = 612.283, 858.898  # taille des modèles d'origine (points)
TEMPLATES_DIR = config.ASSETS_DIR / "invoice_templates"
FONTS_DIR = config.ASSETS_DIR / "fonts"

_FONT_FILES = {
    "TplLato": "Lato-Regular.ttf",
    "TplLato-Bold": "Lato-Bold.ttf",
    "TplLato-Black": "Lato-Black.ttf",
    "TplMont-Medium": "Montserrat-Medium.ttf",
    "TplMont-SemiBold": "Montserrat-SemiBold.ttf",
    "TplMont-Bold": "Montserrat-Bold.ttf",
    "TplMont-ExtraBold": "Montserrat-ExtraBold.ttf",
}
_fonts_ready = False


def _register_fonts() -> None:
    global _fonts_ready
    if _fonts_ready:
        return
    for name, filename in _FONT_FILES.items():
        pdfmetrics.registerFont(TTFont(name, str(FONTS_DIR / filename)))
    _fonts_ready = True


def _palette(style_id: str) -> dict:
    path = TEMPLATES_DIR / "palette.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return data[style_id]


# ── Aides de dessin (coordonnées du modèle : origine en haut à gauche) ───────


class _Pen:
    def __init__(self, canvas, scale: float):
        self.c = canvas
        self.scale = scale  # facteur de la taille de police réglée (1 = taille du modèle)

    def text(self, x, y, value, font, size, color, align="l", max_w=None, min_size=6.0, scaled=True):
        value = "" if value is None else str(value)
        if not value:
            return
        size = size * (self.scale if scaled else 1.0)
        if max_w:
            while size > min_size and pdfmetrics.stringWidth(value, font, size) > max_w:
                size -= 0.25
            if pdfmetrics.stringWidth(value, font, size) > max_w:  # dernier recours : tronquer
                while len(value) > 1 and pdfmetrics.stringWidth(value + "…", font, size) > max_w:
                    value = value[:-1]
                value += "…"
        self.c.setFillColor(HexColor(color) if isinstance(color, str) else color)
        self.c.setFont(font, size)
        yy = TPL_H - y
        if align == "r":
            self.c.drawRightString(x, yy, value)
        elif align == "c":
            self.c.drawCentredString(x, yy, value)
        else:
            self.c.drawString(x, yy, value)

    def wrap(self, value, font, size, max_w, max_lines, scaled=True):
        size = size * (self.scale if scaled else 1.0)
        words = str(value or "").split()
        lines, cur = [], ""
        for word in words:
            trial = f"{cur} {word}".strip()
            if pdfmetrics.stringWidth(trial, font, size) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip(".,; ") + "…"
        return lines

    def rect(self, x0, y0, x1, y1, fill):
        self.c.setFillColor(HexColor(fill))
        self.c.rect(x0, TPL_H - y1, x1 - x0, y1 - y0, stroke=0, fill=1)

    def image(self, path, x0, y0, w, h):
        try:
            self.c.drawImage(str(path), x0, TPL_H - y0 - h, width=w, height=h,
                             preserveAspectRatio=True, mask="auto", anchor="c")
            return True
        except Exception:
            logger.debug("Logo facture ignoré.", exc_info=True)
            return False


# ── Données communes ─────────────────────────────────────────────────────────


def _context(sale, shop):
    from app.printers.invoice_a4 import _vat_included, amount_in_words

    currency = shop.currency or "FCFA"
    items = list(sale.items)
    rate, vat = _vat_included(sale, items)
    moment = sale.date or datetime.now()
    rows = []
    for item in items:
        quantity = float(item.quantity or 0)
        unit_price = float(item.unit_price or 0)
        line_total = float(item.line_total or 0)
        if abs(round(unit_price * quantity, 3) - line_total) > 0.01:
            qty_txt, pu_txt = "—", "—"  # montant libre
        else:
            qty_txt, pu_txt = format_quantity(quantity), format_amount(unit_price)
        rows.append((str(item.product_name or ""), qty_txt, pu_txt, format_amount(line_total)))
    payments = []
    for pay in (sale.payments or []):
        payments.append(f"{pay.method} : {format_money(pay.amount, currency)}")
    if float(sale.amount_received or 0) > 0:
        payments.append(f"Reçu : {format_money(sale.amount_received, currency)}")
        payments.append(f"Monnaie rendue : {format_money(sale.change_due, currency)}")
    logo = Path(str(getattr(shop, "logo_path", "") or ""))
    from app.printers.invoice_a4 import client_refs

    _refs = client_refs(sale)
    return {
        "currency": currency,
        "rows": rows,
        "number": str(sale.ticket_number),
        "date": f"{moment:%d/%m/%Y}",
        "datetime": f"{moment:%d/%m/%Y %H:%M}",
        "cashier": _cashier_name(sale),
        "client": _refs["name"],
        "client_phone": _refs["contact"],
        "client_address": _refs["address"],
        "shop": shop,
        "logo": logo if logo.is_file() else None,
        "subtotal": format_money(sale.subtotal, currency),
        "discount": format_money(sale.discount, currency) if float(sale.discount or 0) > 0 else "",
        "vat": "",  # TVA incluse dans le prix : non affichée sur la facture
        "vat_label": (f"TVA {rate:g} %" if rate else "dont TVA"),
        "total": format_money(sale.total, currency),
        "words": amount_in_words(float(sale.total or 0), currency),
        "payments": payments,
        "footer": str(shop.ticket_footer or ""),
    }


def _shop_lines(shop):
    lines = []
    if shop.phone:
        lines.append(f"Tél. {shop.phone}")
    if shop.email:
        lines.append(str(shop.email))
    if shop.address:
        lines.append(str(shop.address))
    return lines


# ── Modèle « Services » (Lato) ───────────────────────────────────────────────

_SV_ROW0, _SV_PITCH, _SV_ROW_LAST = 375.9, 29.1, 560.0


def _services_page(pen: _Pen, ctx, pal, rows, page, pages):
    ink = pal["ink"]
    shop = ctx["shop"]
    last = page == pages
    # Titre + références
    pen.text(72.6, 134.6, "FACTURE", "TplLato-Black", 40, ink, scaled=False)
    ref = f"N° {ctx['number']}"
    pen.text(72.6, 164.7, ref, "TplLato", 14, ink)
    x_date = 72.6 + pdfmetrics.stringWidth(ref, "TplLato", 14 * pen.scale) + 14
    if x_date + 120 < 440:
        pen.text(x_date, 164.7, f"Date : {ctx['date']}", "TplLato", 14, ink)
    else:
        pen.text(72.6, 164.7 + 17 * pen.scale, f"Date : {ctx['date']}", "TplLato", 14, ink)
    # Logo / nom du commerce (en haut à droite)
    if ctx["logo"]:
        pen.image(ctx["logo"], 441, 92, 100, 44)
        pen.text(541, 154.1, str(shop.name or ""), "TplLato-Black", 14, ink, align="r", max_w=150, scaled=False)
    else:
        pen.text(541, 141.8, str(shop.name or "Commerce").upper(), "TplLato-Black", 17, ink, align="r", max_w=150, scaled=False)
        if shop.phone:
            pen.text(541, 154.1, f"Tél. {shop.phone}", "TplLato", 9, ink, align="r", max_w=150, scaled=False)
    # Émetteur / client (cadre arrondi du modèle)
    pen.text(100.0, 221.8, "Émetteur", "TplLato-Bold", 14, ink)
    left = [str(shop.name or "")] + [ln for ln in (str(shop.email or ""), str(shop.address or "")) if ln]
    if shop.phone and not shop.email:
        left.insert(1, f"Tél. {shop.phone}")
    for i, line in enumerate(left[:3]):
        pen.text(100.0, (241.8, 263.0, 284.5)[i], line, "TplLato", 14, ink, max_w=225, min_size=7)
    pen.text(347.9, 219.4, "Facturé à", "TplLato-Bold", 14, ink)
    right = [ctx["client"]] + [ln for ln in (ctx["client_phone"], ctx["client_address"]) if ln]
    for i, line in enumerate(right[:3]):
        pen.text(347.9, (241.8, 263.0, 284.5)[i], line, "TplLato", 14, ink, max_w=190, min_size=7)
    # Tableau
    pen.text(70.4, 344.0, "DÉSIGNATION", "TplLato-Bold", 14, ink, max_w=190)
    pen.text(268.9, 344.0, "QTÉ", "TplLato-Bold", 14, ink)
    pen.text(379.6, 344.0, "PRIX", "TplLato-Bold", 14, ink)
    pen.text(482.9, 344.0, "TOTAL", "TplLato-Bold", 14, ink)
    pitch = _SV_PITCH * max(1.0, pen.scale)
    for i, (name, qty, pu, total) in enumerate(rows):
        y = _SV_ROW0 + i * pitch
        pen.text(70.4, y, name, "TplLato", 14, ink, max_w=190, min_size=7)
        pen.text(288.5, y, qty, "TplLato", 14, ink, align="c", max_w=60, min_size=7)
        pen.text(446.0, y, pu, "TplLato", 14, ink, align="r", max_w=80, min_size=7)
        pen.text(541.0, y, total, "TplLato", 14, ink, align="r", max_w=90, min_size=7)
    if not last:
        pen.text(541.0, 809.3, f"Suite page suivante — page {page}/{pages}", "TplLato", 10, ink, align="r", scaled=False)
        return
    # Totaux (libellés alignés à droite comme dans le modèle)
    lines = [("Sous-total", ctx["subtotal"])]
    if ctx["discount"]:
        lines.append(("Remise", "- " + ctx["discount"]))
    if ctx["vat"]:
        lines.append((ctx["vat_label"], ctx["vat"]))
    lines.append(("Total", ctx["total"]))
    base = 660.0
    pitch_t = 29.1 if len(lines) <= 3 else 24.0
    for i, (label, value) in enumerate(lines):
        y = base - (len(lines) - 1 - i) * pitch_t
        bold = label == "Total"
        pen.text(414.3, y, label, "TplLato-Black" if bold else "TplLato-Bold", 14, ink, align="r")
        pen.text(541.0, y, value, "TplLato-Bold" if bold else "TplLato", 14, ink, align="r", max_w=115, min_size=7)
    pen.text(164.5, 668.1, "Le responsable", "TplLato", 14, ink, align="c")
    # Arrêté + message
    pen.text(70.4, 705.3, "Arrêtée la facture à la somme de :", "TplLato-Bold", 14, ink, max_w=270, min_size=9)
    y = 725.2
    for line in pen.wrap(ctx["words"] + f" ({ctx['total']})", "TplLato", 12, 262, 3):
        pen.text(70.4, y, line, "TplLato", 12, ink)
        y += 14.4 * max(1.0, pen.scale)
    if ctx["footer"] and y < 770:
        for line in pen.wrap(ctx["footer"], "TplLato", 12, 262, 1):
            pen.text(70.4, y + 4, line, "TplLato", 12, ink)
    # Informations de paiement
    pen.text(362.9, 706.9, "Paiement :", "TplLato-Bold", 14, ink)
    pay = ctx["payments"][:4]
    pitch_p = 21.5 if len(pay) <= 3 else 17.0
    for i, line in enumerate(pay):
        pen.text(362.9, 728.3 + i * pitch_p, line, "TplLato", 14 if len(pay) <= 3 else 12, ink, max_w=180, min_size=7)
    # Pied de page : coordonnées
    contact = "  ·  ".join(_shop_lines(shop))
    if contact:
        pen.text(70.6, 809.3, contact, "TplLato", 10, ink, max_w=470, scaled=False)
    if pages > 1:
        pen.text(541.0, 826.0, f"Page {page}/{pages}", "TplLato", 10, ink, align="r", scaled=False)


# ── Modèle « Médical » (Montserrat) ──────────────────────────────────────────

_MD_BAND_TOP, _MD_BAND_H, _MD_PITCH, _MD_BOTTOM = 338.0, 27.0, 43.2, 541.0


def _medical_layout(n_rows: int):
    """(pitch, hauteur de bande) pour n lignes dans la zone du modèle."""
    if n_rows <= 5:
        return _MD_PITCH, _MD_BAND_H
    bh = max(18.0, min(_MD_BAND_H, 24.0))
    pitch = (_MD_BOTTOM - _MD_BAND_TOP - bh) / (n_rows - 1)
    return pitch, bh


def _medical_page(pen: _Pen, ctx, pal, rows, page, pages):
    ink, blue, band, item_c, foot = pal["ink"], pal["blue"], pal["band"], pal["item"], pal["footer"]
    shop = ctx["shop"]
    last = page == pages
    # Titre + logo
    pen.text(75.2, 190.4, "FACTURE", "TplMont-ExtraBold", 50, blue, scaled=False)
    if ctx["logo"]:
        pen.image(ctx["logo"], 357, 72, 50, 50)
        pen.text(415.0, 107.4, str(shop.name or ""), "TplMont-ExtraBold", 14.2, blue, max_w=150, scaled=False)
    else:
        pen.text(357.0, 107.4, str(shop.name or "Commerce").upper(), "TplMont-ExtraBold", 14.2, blue, max_w=190, scaled=False)
    # Références
    pen.text(358.2, 169.2, f"FACTURE N° {ctx['number']}", "TplMont-SemiBold", 12, ink, max_w=190, min_size=7)
    pen.text(358.2, 183.6, f"DATE : {ctx['datetime']}", "TplMont-SemiBold", 12, ink, max_w=190, min_size=7)
    if ctx["cashier"]:
        pen.text(358.2, 198.0, f"CAISSIER : {ctx['cashier'].upper()}", "TplMont-SemiBold", 12, ink, max_w=190, min_size=7)
    pen.text(360.5, 219.9, "FACTURÉ À :", "TplMont-SemiBold", 12, ink)
    pen.text(360.5, 234.3, ctx["client"].upper(), "TplMont-SemiBold", 12, ink, max_w=185, min_size=7)
    extra = ctx["client_phone"] or ctx["client_address"]
    if extra:
        pen.text(360.5, 248.7, extra.upper(), "TplMont-SemiBold", 12, ink, max_w=185, min_size=7)
    # Tableau : en-tête puis bandes alternées redessinées
    pen.rect(67, 297, 546, 324, blue)
    for x, label in ((95.7, "PRODUIT"), (297.0, "PRIX"), (384.5, "QTÉ"), (461.3, "TOTAL")):
        pen.text(x, 314.8, label, "TplMont-Bold", 12, white)
    pitch, bh = _medical_layout(len(rows))
    for i, (name, qty, pu, total) in enumerate(rows):
        top = _MD_BAND_TOP + i * pitch
        if i % 2 == 0:
            pen.rect(66 if i == 0 else 67, top, 546, top + bh, band)
        base = top + bh * 0.68
        size = 12 if bh >= 27 else 10
        pen.text(95.7, base, name, "TplMont-Bold", size, item_c, max_w=190, min_size=7)
        pen.text(297.0, base, pu, "TplMont-Bold", size, item_c, max_w=82, min_size=7)
        pen.text(395.5 - 11, base, qty, "TplMont-Bold", size, item_c, max_w=60, min_size=7)
        pen.text(461.3, base, total, "TplMont-Bold", size, blue, max_w=85, min_size=7)
    if not last:
        pen.text(546.0, 600.0, f"Suite page suivante — page {page}/{pages}", "TplMont-Medium", 9.4, foot, align="r", scaled=False)
        return
    # Paiement (à gauche)
    pen.text(76.6, 569.5, "PAIEMENT :", "TplMont-Bold", 10, ink)
    for i, line in enumerate(ctx["payments"][:4]):
        pen.text(76.6, 581.5 + 12 * i, line, "TplMont-Bold", 10, ink, max_w=200, min_size=6.5)
    # Totaux (à droite)
    lines = [("SOUS-TOTAL", ctx["subtotal"])]
    if ctx["discount"]:
        lines.append(("REMISE", "- " + ctx["discount"]))
    if ctx["vat"]:
        lines.append((ctx["vat_label"].upper(), ctx["vat"]))
    lines.append(("TOTAL À PAYER", ctx["total"]))
    for i, (label, value) in enumerate(lines):
        y = 570.3 + 20 * i
        pen.text(430.0, y, label, "TplMont-ExtraBold", 11, blue, align="r", max_w=100, min_size=7)
        pen.text(458.7, y, value, "TplMont-Bold", 11, blue, max_w=88, min_size=7)
    # Arrêté + message (centrés)
    pen.text(306.0, 674.1, "ARRÊTÉE LA FACTURE À LA SOMME DE :", "TplMont-Bold", 12, ink, align="c", max_w=420, min_size=8)
    y = 686.1
    for line in pen.wrap(ctx["words"] + f" ({ctx['total']})", "TplMont-Medium", 10, 400, 2):
        pen.text(306.0, y, line, "TplMont-Medium", 10, ink, align="c")
        y += 12.0
    if ctx["footer"] and y <= 710.1:
        pen.text(306.0, y, ctx["footer"], "TplMont-Medium", 10, ink, align="c", max_w=400, min_size=7)
    # Pied de page : téléphone / e-mail / adresse (à côté des pictogrammes du modèle)
    pen.text(106.7, 780.4, str(shop.phone or ""), "TplMont-Medium", 9.4, foot, max_w=110, scaled=False)
    pen.text(241.9, 779.2, str(shop.email or ""), "TplMont-Medium", 9.4, foot, max_w=140, scaled=False)
    pen.text(402.5, 780.0, str(shop.address or ""), "TplMont-Medium", 9.4, foot, max_w=143, scaled=False)
    if pages > 1:
        pen.text(546.0, 826.0, f"Page {page}/{pages}", "TplMont-Medium", 9.4, foot, align="r", scaled=False)


# ── Assemblage ───────────────────────────────────────────────────────────────


def _paginate(rows, per_page_fn):
    """Répartit les lignes sur les pages ; per_page_fn(page_rows_count) -> capacité."""
    capacity = per_page_fn()
    if not rows:
        return [[]]
    return [rows[i:i + capacity] for i in range(0, len(rows), capacity)]


def _cashier_name(sale) -> str:
    try:
        name = getattr(sale, "cashier_name", "") or ""
    except Exception:
        name = ""
    return "" if name == "—" else str(name)


def build_template_invoice(sale, shop, path: Path, style_id: str, font_size: int) -> Path:
    """Génère la facture A4 portrait d'un modèle fidèle (Services / Médical)."""
    from pypdf import PdfReader, PdfWriter

    _register_fonts()
    ctx = _context(sale, shop)
    pal = _palette(style_id)
    family = "services" if style_id.startswith("services") else "medical"
    scale = max(0.7, min(2.0, font_size / 10.0))

    if family == "services":
        pitch = _SV_PITCH * max(1.0, scale)
        cap = max(1, int((_SV_ROW_LAST - _SV_ROW0) // pitch) + 1)
        draw = _services_page
    else:
        cap = 8
        draw = _medical_page
    pages_rows = _paginate(ctx["rows"], lambda: cap)

    buf = BytesIO()
    canvas = rl_canvas.Canvas(buf, pagesize=(TPL_W, TPL_H))
    pen = _Pen(canvas, scale)
    for number, page_rows in enumerate(pages_rows, start=1):
        draw(pen, ctx, pal, page_rows, number, len(pages_rows))
        canvas.showPage()
    canvas.save()
    buf.seek(0)

    overlay = PdfReader(buf)
    writer = PdfWriter()
    a4_w, a4_h = A4
    for page in overlay.pages:
        base = PdfReader(str(TEMPLATES_DIR / f"{style_id}.pdf")).pages[0]
        base.merge_page(page)
        base.cropbox = base.mediabox
        base.scale_to(a4_w, a4_h)
        writer.add_page(base)
    writer.add_metadata({"/Title": f"Facture {sale.ticket_number}", "/Author": str(shop.name or "")})
    with open(path, "wb") as fh:
        writer.write(fh)
    return path
