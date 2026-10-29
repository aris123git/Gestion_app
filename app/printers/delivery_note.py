"""Bon de livraison (PDF A4) : 6 mises en page × 2 couleurs.

Les informations client viennent de la fiche client (nom, téléphones, adresse,
e-mail, n° client) ; celles du commerce viennent des Paramètres. Une ligne sans
donnée n'est pas imprimée. Les prix ne figurent que dans les modèles qui ont
des colonnes de prix (Marine, Cadres, Classique) ; la TVA, incluse dans les
prix, n'est pas affichée.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import BaseDocTemplate, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table, TableStyle

from app import config
from app.printers.invoice_a4 import client_refs, get_font_size
from app.services import settings_service
from app.services.invoice_numbering import delivery_number
from app.utils.helpers import format_amount, format_money

SETTING_ENABLED = "bl_enabled"
SETTING_IN_ALL = "bl_in_all"
SETTING_STYLE = "bl_style"
SETTING_LEGAL = "bl_legal_text"
SETTING_COMMERCIAL = "bon_commercial"
DEFAULT_STYLE = "bandeau_bleu"

W, H = A4
MX = 15 * mm


@dataclass(frozen=True)
class DeliveryStyle:
    id: str
    label: str
    layout: str
    primary: str
    accent: str


DELIVERY_STYLES = [
    DeliveryStyle("bandeau_bleu", "Bandeau bleu — bleu", "bandeau", "#1668f0", "#0f172a"),
    DeliveryStyle("bandeau_vert", "Bandeau bleu — vert", "bandeau", "#15803d", "#0f172a"),
    DeliveryStyle("marine_marine", "Marine — marine", "marine", "#131a33", "#f1f1f4"),
    DeliveryStyle("marine_bordeaux", "Marine — bordeaux", "marine", "#6b1d2e", "#f6eeef"),
    DeliveryStyle("cadres_bleu", "Cadres arrondis — bleu", "cadres", "#2f5a8f", "#2d86a0"),
    DeliveryStyle("cadres_vert", "Cadres arrondis — vert", "cadres", "#2f7a4d", "#5c9e3a"),
    DeliveryStyle("cyan_cyan", "Cyan moderne — cyan", "cyan", "#06a9cf", "#f59e0b"),
    DeliveryStyle("cyan_orange", "Cyan moderne — orange", "cyan", "#ea7a14", "#0f172a"),
    DeliveryStyle("societe_cyan", "Société — cyan", "societe", "#06a9e8", "#4472c4"),
    DeliveryStyle("societe_vert", "Société — vert", "societe", "#16a34a", "#166534"),
    DeliveryStyle("classique_vert", "Classique noir — vert", "classique", "#7a9a20", "#000000"),
    DeliveryStyle("classique_rouge", "Classique noir — rouge", "classique", "#b91c1c", "#000000"),
]
_BY_ID = {s.id: s for s in DELIVERY_STYLES}
WITH_PRICES = {"marine", "cadres", "classique"}


def get_style(style_id: str | None = None) -> DeliveryStyle:
    key = (style_id or settings_service.get_setting(SETTING_STYLE, DEFAULT_STYLE)).strip()
    return _BY_ID.get(key, _BY_ID[DEFAULT_STYLE])


def is_enabled() -> bool:
    return settings_service.get_setting(SETTING_ENABLED, "0").strip() == "1"


def in_print_all() -> bool:
    return settings_service.get_setting(SETTING_IN_ALL, "1").strip() == "1"


# --- données ----------------------------------------------------------------
def _product_info(sale) -> dict:
    ids = {i.product_id for i in sale.items if getattr(i, "product_id", None)}
    if not ids:
        return {}
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        from app.database.connection import session_scope
        from app.models.product import Product

        with session_scope() as session:
            rows = session.scalars(select(Product).options(joinedload(Product.unit)).where(Product.id.in_(ids))).unique().all()
            return {p.id: ((p.reference or p.barcode or "").strip(), p.unit.name if p.unit else "") for p in rows}
    except Exception:
        return {}


def _fit(canvas, text: str, font: str, size: float, max_w: float) -> tuple[str, float]:
    """Réduit la police (jusqu'à 60 %) puis tronque pour tenir dans ``max_w``."""
    text = str(text or "")
    s = size
    while s > size * 0.6 and stringWidth(text, font, s) > max_w:
        s -= 0.5
    while text and stringWidth(text, font, s) > max_w:
        text = text[:-1]
    return text, s


def _text(canvas, x, y, text, font="Helvetica", size=9, color="#111827", align="l", max_w=None):
    if not str(text or "").strip():
        return
    canvas.setFillColor(HexColor(color) if isinstance(color, str) else color)
    if max_w:
        text, size = _fit(canvas, text, font, size, max_w)
    canvas.setFont(font, size)
    {"l": canvas.drawString, "r": canvas.drawRightString, "c": canvas.drawCentredString}[align](x, y, str(text))


@dataclass
class Ctx:
    style: DeliveryStyle
    shop: object
    currency: str
    number: str
    day: datetime
    sale_ref: str
    refs: dict
    client_no: str
    commercial: str
    place: str
    info_msg: str
    legal: str
    rccm: str
    ifu: str
    bank: str
    bank_name: str
    logo: Optional[Path]
    rows: list  # (réf, désignation, qté, unité, pu, total)
    total: float
    fs: int


def _build_ctx(sale, shop, selected, style_id, overrides, font_size) -> Ctx:
    from app.printers.bon_enlevement import _opt

    items = list(sale.items)
    chosen = set(range(len(items))) if selected is None else {int(i) for i in selected}
    picked = [it for i, it in enumerate(items) if i in chosen]
    if not picked:
        raise ValueError("Aucun produit sélectionné pour le bon de livraison.")
    info = _product_info(sale)
    rows, total = [], 0.0
    for it in picked:
        ref, unit = info.get(getattr(it, "product_id", None) or -1, ("", ""))
        qty, pu, lt = float(it.quantity or 0), float(it.unit_price or 0), float(it.line_total or 0)
        total += lt
        rows.append((ref, str(it.product_name or ""), qty, unit, pu, lt))
    refs = client_refs(sale)
    client_id = getattr(sale, "client_id", None)
    try:
        client = getattr(sale, "client", None)
        client_id = client_id or (client.id if client is not None else None)
    except Exception:
        pass
    logo = Path(str(getattr(shop, "logo_path", "") or ""))
    address = str(shop.address or "")
    place = address.split(",")[-1].strip() if address else ""
    return Ctx(
        style=get_style(style_id), shop=shop, currency=shop.currency or "FCFA", number=delivery_number(sale),
        day=sale.date or datetime.now(), sale_ref=str(sale.ticket_number or ""), refs=refs,
        client_no=f"{int(client_id):05d}" if client_id else "", commercial=_opt(SETTING_COMMERCIAL, overrides),
        place=place, info_msg=str(getattr(shop, "ticket_footer", "") or "").strip(),
        legal=_opt(SETTING_LEGAL, overrides), rccm=_opt("shop_rccm", overrides), ifu=_opt("shop_ifu", overrides),
        bank=_opt("shop_bank_account", overrides), bank_name=_opt("shop_bank_name", overrides), logo=logo if logo.is_file() else None, rows=rows, total=total,
        fs=max(7, min(13, int(font_size or get_font_size()) - 1)),
    )


def _shop_contact_lines(c: Ctx) -> list[str]:
    s = c.shop
    return [x for x in (str(s.address or ""), f"Tél : {s.phone}" if s.phone else "", str(s.email or "")) if x]


def _client_lines(c: Ctx) -> list[str]:
    r = c.refs
    if not r.get("known"):
        return []
    out = []
    if r.get("address"):
        out.append(r["address"])
    if r.get("contact"):
        out.append(f"Tél : {r['contact']}")
    if r.get("email"):
        out.append(r["email"])
    return out


def _client_name(c: Ctx) -> str:
    return c.refs["name"] if c.refs.get("known") else ""


def _draw_logo(canvas, c: Ctx, x, y, w, h):
    if c.logo:
        try:
            canvas.drawImage(str(c.logo), x, y, w, h, preserveAspectRatio=True, mask="auto", anchor="c")
            return True
        except Exception:
            return False
    return False


def _para(c: Ctx, size=None, bold=False, color="#111827", align=0):
    size = size or c.fs
    return ParagraphStyle("p", fontName="Helvetica-Bold" if bold else "Helvetica", fontSize=size, leading=size * 1.3, textColor=HexColor(color), alignment=align)


def _money(c: Ctx, v: float) -> str:
    return format_money(v, c.currency)


def _footer_cols(canvas, c: Ctx, titles_cols, y0, bar_color=None):
    """Pied de page à 3 colonnes (titre gras + lignes)."""
    x = MX
    colw = (W - 2 * MX) / 3
    for i, (title, lines) in enumerate(titles_cols):
        if not lines:
            continue
        _text(canvas, x + i * colw, y0, title, "Helvetica-Bold", 7.5, "#111827")
        for j, ln in enumerate(lines[:5]):
            _text(canvas, x + i * colw, y0 - 4 * mm - j * 3.6 * mm, ln, "Helvetica", 7, "#374151", max_w=colw - 4 * mm)
    if bar_color:
        canvas.setFillColor(HexColor(bar_color))
        canvas.rect(0, 0, W, 6 * mm, stroke=0, fill=1)


# ---------------------------------------------------------------------------------
# Modèle 1 — Bandeau (type « CSMART »)
# ---------------------------------------------------------------------------------
def _layout_bandeau(c: Ctx):
    p, dark = HexColor(c.style.primary), HexColor(c.style.accent)

    def first(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(p)
        canvas.rect(0, H - 22 * mm, W, 22 * mm, stroke=0, fill=1)
        _text(canvas, MX, H - 11 * mm, str(c.shop.phone or ""), "Helvetica", 8, "#ffffff")
        _text(canvas, MX, H - 15 * mm, str(c.shop.email or ""), "Helvetica", 8, "#ffffff")
        _text(canvas, W - MX, H - 14 * mm, str(c.shop.name or "").upper(), "Helvetica", 18, "#ffffff", "r", max_w=W - 2 * MX - 60 * mm)
        _text(canvas, W / 2, H - 42 * mm, "BON DE LIVRAISON", "Helvetica", 28, c.style.accent, "c")
        canvas.setStrokeColor(dark)
        canvas.setLineWidth(1)
        canvas.line(W / 2 - 35 * mm, H - 49 * mm, W / 2 + 35 * mm, H - 49 * mm)
        left = [("BL numéro :", c.number), ("Date :", f"{c.day:%d / %m / %Y}")]
        if c.shop.phone:
            left.append(("Tél. :", str(c.shop.phone)))
        right = []
        if c.refs.get("known"):
            right.append(("Nom :", c.refs["name"]))
            if c.refs.get("address"):
                right.append(("Adresse :", c.refs["address"]))
            if c.refs.get("email"):
                right.append(("Email :", c.refs["email"]))
        y = H - 62 * mm
        for i, (lab, val) in enumerate(left):
            _text(canvas, MX, y - i * 7 * mm, lab, "Helvetica", 9, "#111827")
            _text(canvas, MX + 24 * mm, y - i * 7 * mm, val, "Helvetica-Bold", 9, "#111827", max_w=60 * mm)
            canvas.setLineWidth(0.4)
            canvas.line(MX + 24 * mm, y - i * 7 * mm - 1.3 * mm, MX + 84 * mm, y - i * 7 * mm - 1.3 * mm)
        for i, (lab, val) in enumerate(right):
            _text(canvas, W / 2 + 5 * mm, y - i * 7 * mm, lab, "Helvetica", 9, "#111827")
            _text(canvas, W / 2 + 27 * mm, y - i * 7 * mm, val, "Helvetica-Bold", 9, "#111827", max_w=W / 2 - MX - 27 * mm - 5 * mm)
            canvas.line(W / 2 + 27 * mm, y - i * 7 * mm - 1.3 * mm, W - MX, y - i * 7 * mm - 1.3 * mm)
        y2 = y - 3 * 7 * mm - 1 * mm
        _text(canvas, MX, y2, "Réf. vente :", "Helvetica", 9, "#111827")
        _text(canvas, MX + 24 * mm, y2, c.sale_ref, "Helvetica-Bold", 9, "#111827", max_w=60 * mm)
        if c.client_no:
            _text(canvas, W / 2 + 5 * mm, y2, "Numéro client :", "Helvetica", 9, "#111827")
            _text(canvas, W / 2 + 33 * mm, y2, c.client_no, "Helvetica-Bold", 9, "#111827")
        canvas.restoreState()

    def later(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(p)
        canvas.rect(0, H - 10 * mm, W, 10 * mm, stroke=0, fill=1)
        _text(canvas, MX, H - 6.5 * mm, f"BON DE LIVRAISON N° {c.number}", "Helvetica-Bold", 9, "#ffffff")
        canvas.restoreState()

    fs = c.fs
    head = [Paragraph(x, _para(c, fs - 1, True, "#111827")) for x in ("RÉF PRODUIT", "DESCRIPTION", "QUANTITÉ", "UNITÉ")]
    data = [head] + [[Paragraph(r[0], _para(c)), Paragraph(r[1], _para(c)), f"{r[2]:g}", r[3]] for r in c.rows]
    cw = [(W - 2 * MX) * x for x in (0.18, 0.46, 0.18, 0.18)]
    t = Table(data, colWidths=cw, repeatRows=1)
    pad = max(3, fs * 0.55)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.8, dark), ("FONTSIZE", (0, 0), (-1, -1), fs), ("ALIGN", (2, 0), (-1, -1), "CENTER"),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad)]))
    foot = Table([[Paragraph(f"Reçu le : ______________________", _para(c)), Paragraph(f"Livré le : {c.day:%d/%m/%Y}", _para(c))]], colWidths=[(W - 2 * MX) / 2] * 2)
    notes = Table([[Paragraph("NOTES :", _para(c, fs, False)), "", Paragraph("Signature :", _para(c))]], colWidths=[(W - 2 * MX) * 0.45, (W - 2 * MX) * 0.1, (W - 2 * MX) * 0.45], rowHeights=[38 * mm])
    notes.setStyle(TableStyle([("BOX", (0, 0), (0, 0), 0.8, dark), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4)]))
    story = [t, Spacer(1, 8 * mm), KeepTogether([foot, Spacer(1, 6 * mm), notes])]
    return story, first, later, 92 * mm, 14 * mm


# ---------------------------------------------------------------------------------
# Modèle 2 — Marine
# ---------------------------------------------------------------------------------
def _layout_marine(c: Ctx):
    navy = HexColor(c.style.primary)
    grey = HexColor(c.style.accent)

    def first(canvas, doc):
        canvas.saveState()
        top = H - 18 * mm
        canvas.setFillColor(navy)
        canvas.rect(MX, top - 24 * mm, 100 * mm, 24 * mm, stroke=0, fill=1)
        _text(canvas, MX + 50 * mm, top - 14 * mm, "BON DE LIVRAISON", "Helvetica-Bold", 17, "#ffffff", "c", max_w=92 * mm)
        bx = W - MX - 52 * mm
        canvas.setStrokeColor(navy)
        canvas.setLineWidth(0.8)
        canvas.setFillColor(navy)
        canvas.rect(bx, top - 5 * mm, 52 * mm, 5 * mm, stroke=1, fill=1)
        _text(canvas, bx + 26 * mm, top - 3.7 * mm, "N° BL", "Helvetica-Bold", 8, "#ffffff", "c")
        canvas.setFillColor(colors.white)
        canvas.rect(bx, top - 12 * mm, 52 * mm, 7 * mm, stroke=1, fill=0)
        _text(canvas, bx + 26 * mm, top - 10 * mm, c.number, "Helvetica-Bold", 9, "#111827", "c")
        canvas.setFillColor(navy)
        canvas.rect(bx, top - 17 * mm, 52 * mm, 5 * mm, stroke=1, fill=1)
        for i, lab in enumerate(("Jour", "Mois", "Année")):
            _text(canvas, bx + (i + 0.5) * 52 / 3 * mm, top - 15.7 * mm, lab, "Helvetica-Bold", 8, "#ffffff", "c")
        canvas.setFillColor(colors.white)
        canvas.rect(bx, top - 24 * mm, 52 * mm, 7 * mm, stroke=1, fill=0)
        for i, val in enumerate((f"{c.day:%d}", f"{c.day:%m}", f"{c.day:%Y}")):
            _text(canvas, bx + (i + 0.5) * 52 / 3 * mm, top - 22 * mm, val, "Helvetica", 9, "#111827", "c")
            if i:
                canvas.line(bx + i * 52 / 3 * mm, top - 24 * mm, bx + i * 52 / 3 * mm, top - 17 * mm)
        _text(canvas, W / 2, top - 36 * mm, "Données Clients", "Helvetica-Bold", 12, c.style.primary, "c")
        canvas.setStrokeColor(HexColor(c.style.primary))
        canvas.line(W / 2 - 22 * mm, top - 37.2 * mm, W / 2 + 22 * mm, top - 37.2 * mm)
        yb = top - 52 * mm
        for x, w, rows in ((MX, 112 * mm, [("Nom :", _client_name(c)), ("Adresse :", c.refs.get("address", "") if c.refs.get("known") else "")]),
                           (MX + 118 * mm, W - 2 * MX - 118 * mm, [("N° Client :", c.client_no), ("Contact :", c.refs.get("contact", "") if c.refs.get("known") else "")])):
            rows = [r for r in rows if r[1]] or [rows[0]]
            hh = 5.5 * mm * len(rows)
            canvas.setStrokeColor(HexColor("#111827"))
            canvas.rect(x, yb - hh, w, hh, stroke=1, fill=0)
            for i, (lab, val) in enumerate(rows):
                yy = yb - (i + 0.7) * 5.5 * mm
                _text(canvas, x + 2 * mm, yy, lab, "Helvetica-Bold", 8.5, "#111827")
                _text(canvas, x + 2 * mm + stringWidth(lab, "Helvetica-Bold", 8.5) + 2 * mm, yy, val, "Helvetica", 8.5, "#111827", max_w=w - 28 * mm)
                if i:
                    canvas.line(x, yb - i * 5.5 * mm, x + w, yb - i * 5.5 * mm)
        canvas.restoreState()

    def later(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(navy)
        canvas.rect(MX, H - 14 * mm, W - 2 * MX, 7 * mm, stroke=0, fill=1)
        _text(canvas, MX + 3 * mm, H - 11.5 * mm, f"BON DE LIVRAISON N° {c.number}", "Helvetica-Bold", 9, "#ffffff")
        canvas.restoreState()

    fs = c.fs
    head = ["Référence", "Quantité", "Description", "Prix unitaire", "Prix total"]
    data = [head] + [[Paragraph(r[0], _para(c)), f"{r[2]:g}", Paragraph(r[1], _para(c)), format_amount(r[4]), format_amount(r[5])] for r in c.rows]
    cw = [(W - 2 * MX) * x for x in (0.14, 0.11, 0.41, 0.17, 0.17)]
    t = Table(data, colWidths=cw, repeatRows=1)
    pad = max(4, fs * 0.8)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                           ("FONTSIZE", (0, 0), (-1, -1), fs), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [grey, colors.white]), ("GRID", (0, 1), (-1, -1), 0.4, HexColor("#cbd5e1")),
                           ("ALIGN", (1, 0), (1, -1), "CENTER"), ("ALIGN", (3, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad)]))
    tot = Table([["Total", _money(c, c.total)]], colWidths=[28 * mm, 40 * mm])
    tot.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, HexColor("#111827")), ("INNERGRID", (0, 0), (-1, -1), 0.6, HexColor("#111827")), ("ALIGN", (0, 0), (0, -1), "RIGHT"),
                             ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), fs), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    sign = Table([[Paragraph("<u>&nbsp;" + "&nbsp;" * 34 + "</u><br/>Reçoit Conforme", _para(c, fs, False, "#111827", 1)), tot]], colWidths=[(W - 2 * MX) - 70 * mm, 70 * mm])
    sign.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
    story = [t, Spacer(1, 10 * mm), KeepTogether([sign])]
    return story, first, later, 98 * mm, 14 * mm


# ---------------------------------------------------------------------------------
# Modèle 3 — Cadres arrondis
# ---------------------------------------------------------------------------------
def _layout_cadres(c: Ctx):
    blue, teal, navy = HexColor(c.style.primary), HexColor(c.style.accent), HexColor("#10233f")

    def first(canvas, doc):
        canvas.saveState()
        top = H - 14 * mm
        if c.logo:
            _draw_logo(canvas, c, MX, top - 34 * mm, 48 * mm, 34 * mm)
        else:
            _text(canvas, MX, top - 12 * mm, str(c.shop.name or ""), "Helvetica-Bold", 14, c.style.primary, max_w=70 * mm)
        info = [str(c.shop.address or ""), f"Téléphone : {c.shop.phone}" if c.shop.phone else "", f"Adresse mail : {c.shop.email}" if c.shop.email else ""]
        for i, ln in enumerate([x for x in info if x]):
            _text(canvas, MX, top - 40 * mm - i * 4.2 * mm, ln, "Helvetica-Oblique", 8, "#111827", max_w=70 * mm)
        canvas.setStrokeColor(blue)
        canvas.setLineWidth(1.6)
        canvas.roundRect(W - MX - 110 * mm, top - 14 * mm, 110 * mm, 13 * mm, 3 * mm, stroke=1, fill=0)
        _text(canvas, W - MX - 105 * mm, top - 9 * mm, "Bon de livraison", "Times-Bold", 14, "#111827")
        _text(canvas, W - MX - 22 * mm, top - 9 * mm, f"N° {c.number}", "Times-Bold", 14, "#111827", "r")
        yy = top - 24 * mm
        for lab, val in (("En date du", f"{c.day:%d/%m/%Y}"), ("Référence vente", c.sale_ref), ("Référence client", c.client_no), ("A l'attention de", _client_name(c))):
            if not val:
                continue
            _text(canvas, W - MX - 110 * mm, yy, lab, "Times-Roman", 9, "#111827")
            _text(canvas, W - MX - 70 * mm, yy, val, "Times-Bold", 9.5, "#111827", max_w=70 * mm)
            yy -= 4.6 * mm
        if c.refs.get("known"):
            bh = 28 * mm
            canvas.roundRect(W - MX - 110 * mm, top - 78 * mm, 110 * mm, bh, 4 * mm, stroke=1, fill=0)
            _text(canvas, W - MX - 104 * mm, top - 58 * mm, c.refs["name"], "Times-Bold", 11, "#111827", max_w=98 * mm)
            for i, ln in enumerate(_client_lines(c)[:3]):
                _text(canvas, W - MX - 104 * mm, top - 63.5 * mm - i * 4.6 * mm, ln, "Times-Roman", 9, "#111827", max_w=98 * mm)
        canvas.restoreState()
        _cadres_footer(canvas)

    def _cadres_footer(canvas):
        ids = "  -  ".join(x for x in (f"N° RCCM {c.rccm}" if c.rccm else "", f"N° IFU {c.ifu}" if c.ifu else "", f"{c.bank_name + ' ' if c.bank_name else ''}Compte {c.bank}" if c.bank else (c.bank_name or "")) if x)
        if ids:
            canvas.saveState()
            _text(canvas, W / 2, 8 * mm, ids, "Times-Roman", 7.5, "#111827", "c", max_w=W - 2 * MX)
            canvas.restoreState()

    def later(canvas, doc):
        canvas.saveState()
        _text(canvas, MX, H - 10 * mm, f"Bon de livraison N° {c.number}", "Times-Bold", 11, "#111827")
        canvas.restoreState()
        _cadres_footer(canvas)

    fs = c.fs
    head = ["Désignation", "Qté", "Prix", "Montant TTC"]
    data = [head] + [[Paragraph(r[1], _para(c)), f"{r[2]:g}", format_amount(r[4]), format_amount(r[5])] for r in c.rows]
    cw = [(W - 2 * MX) * x for x in (0.52, 0.10, 0.18, 0.20)]
    t = Table(data, colWidths=cw, repeatRows=1)
    pad = max(2.5, fs * 0.4)
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, 0), "Times-Bold"), ("FONTSIZE", (0, 0), (-1, 0), fs + 2), ("FONTSIZE", (0, 1), (-1, -1), fs), ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
                           ("LINEAFTER", (0, 0), (2, -1), 0.8, colors.black), ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("ALIGN", (1, 0), (1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad)]))
    total_bar = Table([[Paragraph("<b>TOTAL TTC</b>", _para(c, fs, False, "#ffffff")), Paragraph(f"<b>{_money(c, c.total)}</b>", _para(c, fs + 1, False, "#ffffff", 2))]], colWidths=[34 * mm, 48 * mm])
    total_bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), navy), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    obs = Table([[Paragraph("<b>Observation(s) lors de la réception</b>", _para(c, fs - 1))]], colWidths=[(W - 2 * MX) * 0.55], rowHeights=[20 * mm])
    obs.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ROUNDEDCORNERS", [8, 8, 8, 8]), ("BOX", (0, 0), (-1, -1), 1.6, blue)]))
    sign = Table([[Paragraph("<b>Nom, signature et date du réceptionnaire</b>", _para(c, fs - 1))]], colWidths=[(W - 2 * MX) * 0.45], rowHeights=[26 * mm])
    sign.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ROUNDEDCORNERS", [8, 8, 8, 8]), ("BOX", (0, 0), (-1, -1), 1.6, blue)]))
    lower = Table([[[obs, Spacer(1, 6 * mm), sign], total_bar]], colWidths=[(W - 2 * MX) * 0.60, (W - 2 * MX) * 0.40])
    lower.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story = [t, Spacer(1, 8 * mm), KeepTogether([lower])]
    return story, first, later, 104 * mm, 16 * mm


# ---------------------------------------------------------------------------------
# Modèles 4 et 5 — Cyan moderne / Société
# ---------------------------------------------------------------------------------
def _layout_cyan(c: Ctx, societe: bool = False):
    cy = HexColor(c.style.primary)
    acc = HexColor(c.style.accent)
    grey = HexColor("#f1f1f1")

    def decor(canvas, first_page: bool):
        canvas.saveState()
        top = H - 14 * mm
        if societe:
            if not _draw_logo(canvas, c, MX, top - 24 * mm, 24 * mm, 24 * mm):
                canvas.setFillColor(acc)
                canvas.rect(MX, top - 24 * mm, 24 * mm, 24 * mm, stroke=0, fill=1)
                _text(canvas, MX + 12 * mm, top - 13 * mm, str(c.shop.name or "")[:8], "Helvetica-Bold", 8, "#ffffff", "c", max_w=22 * mm)
            _text(canvas, MX + 34 * mm, top - 16 * mm, "Bon de livraison", "Helvetica-Bold", 28, c.style.primary)
        else:
            _text(canvas, MX, top - 12 * mm, "Bon de livraison", "Helvetica-Bold", 28, c.style.primary)
            if not _draw_logo(canvas, c, W - MX - 22 * mm, top - 22 * mm, 22 * mm, 22 * mm):
                canvas.setFillColor(acc)
                canvas.circle(W - MX - 11 * mm, top - 11 * mm, 11 * mm, stroke=0, fill=1)
                _text(canvas, W - MX - 11 * mm, top - 12.5 * mm, str(c.shop.name or "")[:6], "Helvetica-Bold", 8, "#ffffff", "c", max_w=20 * mm)
        canvas.setStrokeColor(cy)
        canvas.setLineWidth(1.4)
        canvas.line(MX, top - 30 * mm, W - MX, top - 30 * mm)
        if first_page:
            y = top - 40 * mm
            _text(canvas, MX, y, str(c.shop.name or ""), "Helvetica-Bold" if societe else "Helvetica-BoldOblique", 10, "#111827", max_w=90 * mm)
            sl = _shop_contact_lines(c) + ([f"N° RCCM : {c.rccm}"] if societe and c.rccm else []) + ([f"N° IFU : {c.ifu}"] if societe and c.ifu else [])
            for i, ln in enumerate(sl[:5]):
                _text(canvas, MX, y - (i + 1) * 4.6 * mm, ln, "Helvetica" if societe else "Helvetica-Oblique", 8.5, "#374151", max_w=90 * mm)
            # cadre d'informations
            bx, bw = MX, 88 * mm
            fields = [("Bon de livraison N° :", c.number), ("Date :", f"{c.day:%d/%m/%Y}"), ("Lieu :", c.place), ("Référence vente :", c.sale_ref)]
            if not societe:
                fields += [("Numéro de client :", c.client_no), ("Contact client :", c.refs.get("name", "") if c.refs.get("known") else ""), ("Émis par :", c.commercial)]
            fields = [f for f in fields if f[1]]
            bh = 5.2 * mm * len(fields) + 6 * mm
            by = top - (44 + 4.6 * (len(sl[:5]) + 1)) * mm - bh
            canvas.setFillColor(grey)
            canvas.rect(bx, by, bw, bh, stroke=0, fill=1)
            ytop = by + bh - 6.5 * mm
            for i, (lab, val) in enumerate(fields):
                _text(canvas, bx + 4 * mm, ytop - i * 5.2 * mm, lab, "Helvetica", 8.5, "#4b5563")
                _text(canvas, bx + 42 * mm, ytop - i * 5.2 * mm, val, "Helvetica-Bold" if not societe else "Helvetica", 8.5, "#111827", max_w=bw - 46 * mm)
            # destinataire / client
            rx = W / 2 + 8 * mm
            if c.refs.get("known"):
                _text(canvas, rx, top - 50 * mm, "Client :" if societe else "Destinataire", "Helvetica-Bold", 10, "#111827")
                _text(canvas, rx, top - 56 * mm, c.refs["name"], "Helvetica-Bold" if not societe else "Helvetica", 9.5, "#111827", max_w=W - MX - rx)
                extra = []
                if c.client_no and societe:
                    extra.append(f"N° client : {c.client_no}")
                extra += _client_lines(c)
                for i, ln in enumerate(extra[:4]):
                    _text(canvas, rx, top - 61.5 * mm - i * 4.8 * mm, ln, "Helvetica", 8.5, "#374151", max_w=W - MX - rx)
            if c.info_msg:
                _text(canvas, MX, by - 8 * mm, "Informations additionnelles", "Helvetica-Bold", 9.5, "#111827")
                _text(canvas, MX, by - 13.5 * mm, c.info_msg, "Helvetica", 8.5, "#374151", max_w=W - 2 * MX)
        else:
            _text(canvas, MX, top - 38 * mm, f"Bon de livraison N° {c.number}", "Helvetica-Bold", 10, "#111827")
        # pied de page
        cols = [("Siège social", [str(c.shop.address or "")] + ([f"Tél : {c.shop.phone}"] if c.shop.phone else [])),
                ("Informations officielles" if societe else "Coordonnées", ([f"RC : {c.rccm}"] if c.rccm else []) + ([f"IF : {c.ifu}"] if c.ifu else []) if societe else
                 ([c.commercial] if c.commercial else []) + ([f"Phone : {c.shop.phone}"] if c.shop.phone else []) + ([f"E-mail : {c.shop.email}"] if c.shop.email else [])),
                ("Détails bancaires", [x for x in (c.bank_name, c.bank) if x])]
        cols = [(t_, [x for x in lines if x]) for t_, lines in cols]
        _footer_cols(canvas, c, cols, 30 * mm, c.style.primary)
        canvas.restoreState()

    def first(canvas, doc):
        decor(canvas, True)

    def later(canvas, doc):
        decor(canvas, False)

    fs = c.fs
    head = [Paragraph(f"<b>{x}</b>", _para(c, fs - 1)) for x in ("Réf. produit", "Description", "Quantités commandées", "Unité")]
    data = [head] + [[Paragraph(r[0], _para(c, fs, False, "#6b7280")), Paragraph(r[1], _para(c, fs, False, "#4b5563")), f"{r[2]:g}", r[3]] for r in c.rows]
    cw = [(W - 2 * MX) * x for x in (0.18, 0.44, 0.22, 0.16)]
    t = Table(data, colWidths=cw, repeatRows=1)
    pad = max(3, fs * 0.5)
    t.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 1.2, cy), ("LINEBELOW", (0, 0), (-1, 0), 0.6, HexColor("#cbd5e1")), ("LINEBELOW", (0, 1), (-1, -1), 0.3, HexColor("#e5e7eb")),
                           ("FONTSIZE", (0, 0), (-1, -1), fs), ("TEXTCOLOR", (2, 1), (-1, -1), HexColor("#4b5563")), ("ALIGN", (2, 0), (2, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad)]))
    visa_l = [Paragraph("<b>Visa du client</b>", _para(c)), Paragraph("Reçu le : ____ / ____ / ________", _para(c)), Spacer(1, 4 * mm), Paragraph("Signature : ______________________", _para(c))]
    visa_r = [Paragraph("<b>Visa du fournisseur</b>", _para(c)), Paragraph(f"Livré le : {c.day:%d/%m/%Y}", _para(c))]
    vt = Table([[visa_l, visa_r]], colWidths=[(W - 2 * MX) * 0.5] * 2)
    vt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story = [t, Spacer(1, 10 * mm), KeepTogether([vt])]
    nfields = 4 + (0 if societe else 3) - (0 if c.place else 1) - (0 if societe or c.client_no else 1) - (0 if societe or c.refs.get("known") else 1) - (0 if societe or c.commercial else 1)
    nshop = min(5, len(_shop_contact_lines(c)) + (1 if societe and c.rccm else 0) + (1 if societe and c.ifu else 0)) + 1
    top_m = 14 + 44 + 4.6 * nshop + 5.2 * max(nfields, 1) + 6 + (22 if c.info_msg else 6)
    return story, first, later, top_m * mm, 36 * mm


def _layout_societe(c: Ctx):
    return _layout_cyan(c, societe=True)


# ---------------------------------------------------------------------------------
# Modèle 6 — Classique (en-tête sombre, tableau noir)
# ---------------------------------------------------------------------------------
def _layout_classique(c: Ctx):
    green = HexColor(c.style.primary)
    black = HexColor(c.style.accent)

    def decor(canvas, first_page: bool):
        canvas.saveState()
        canvas.setFillColor(black)
        canvas.rect(0, H - 12 * mm, W, 12 * mm, stroke=0, fill=1)
        canvas.setFillColor(green)
        canvas.rect(0, H - 14.5 * mm, W, 2.5 * mm, stroke=0, fill=1)
        _text(canvas, MX, H - 8 * mm, str(c.shop.name or ""), "Helvetica-Bold", 10, "#ffffff", max_w=100 * mm)
        if first_page:
            if not _draw_logo(canvas, c, W - MX - 40 * mm, H - 46 * mm, 40 * mm, 26 * mm):
                _text(canvas, W - MX, H - 34 * mm, str(c.shop.name or "").upper(), "Helvetica-Bold", 20, c.style.primary, "r", max_w=W / 2 - MX)
            if c.refs.get("known"):
                _text(canvas, W / 2 - 10 * mm, H - 64 * mm, c.refs["name"], "Helvetica", 9.5, "#111827", max_w=W / 2 - MX)
                for i, ln in enumerate(_client_lines(c)[:3]):
                    _text(canvas, W / 2 - 10 * mm, H - 69 * mm - i * 4.6 * mm, ln, "Helvetica", 9.5, "#111827", max_w=W / 2 - MX)
            _text(canvas, W - MX, H - 86 * mm, f"{c.place + ', ' if c.place else ''}le {c.day:%d/%m/%Y}", "Helvetica-Oblique", 8.5, "#111827", "r")
            _text(canvas, W / 2, H - 98 * mm, f"Bon de livraison N° {c.number}", "Helvetica-Bold", 12, "#111827", "c")
            if c.sale_ref:
                _text(canvas, W / 2, H - 104 * mm, f"Réf. vente {c.sale_ref}", "Helvetica-Bold", 9, "#111827", "c")
        else:
            _text(canvas, W / 2, H - 22 * mm, f"Bon de livraison N° {c.number}", "Helvetica-Bold", 11, "#111827", "c")
        foot = [str(c.shop.name or "")]
        ids = "  ·  ".join(x for x in (f"N° RCCM {c.rccm}" if c.rccm else "", f"N° IFU {c.ifu}" if c.ifu else "", f"{c.bank_name + ' ' if c.bank_name else ''}RIB {c.bank}" if c.bank else (c.bank_name or "")) if x)
        _text(canvas, MX, 22 * mm, foot[0], "Helvetica-Bold", 14, "#111827", max_w=W - 2 * MX)
        _text(canvas, MX, 16 * mm, ids, "Helvetica", 7.5, c.style.primary, max_w=W - 2 * MX)
        contact = "  ·  ".join(_shop_contact_lines(c))
        _text(canvas, MX, 11 * mm, contact, "Helvetica", 7.5, "#374151", max_w=W - 2 * MX)
        canvas.restoreState()

    def first(canvas, doc):
        decor(canvas, True)

    def later(canvas, doc):
        decor(canvas, False)

    fs = c.fs
    head = ["Détails", "Qté", "Unité", "PU", "Total"]
    data = [head] + [[Paragraph(r[1], _para(c)), f"{r[2]:g}", r[3], format_amount(r[4]), format_amount(r[5])] for r in c.rows]
    cw = [(W - 2 * MX) * x for x in (0.44, 0.10, 0.12, 0.17, 0.17)]
    t = Table(data, colWidths=cw, repeatRows=1)
    pad = max(2.5, fs * 0.4)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), black), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), fs),
                           ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("ALIGN", (0, 0), (0, 0), "CENTER"), ("ALIGN", (1, 0), (2, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad)]))
    tot = Table([["TOTAL", _money(c, c.total)]], colWidths=[28 * mm, 42 * mm])
    tot.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), black), ("TEXTCOLOR", (0, 0), (-1, -1), colors.white), ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), fs),
                             ("ALIGN", (1, 0), (1, 0), "RIGHT"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    parts = [Table([["", tot]], colWidths=[(W - 2 * MX) - 70 * mm, 70 * mm], style=[("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]), Spacer(1, 8 * mm)]
    if c.legal:
        parts.append(Paragraph(c.legal, _para(c, fs - 1)))
    parts += [Spacer(1, 2 * mm), Paragraph("<b>Réserve(s), date et signature du réceptionnaire :</b>", _para(c, fs - 1))]
    story = [t, Spacer(1, 6 * mm), KeepTogether(parts)]
    return story, first, later, 112 * mm, 36 * mm


_LAYOUTS = {"bandeau": _layout_bandeau, "marine": _layout_marine, "cadres": _layout_cadres, "cyan": _layout_cyan, "societe": _layout_societe, "classique": _layout_classique}


def selectable_lines(sale) -> list[tuple[int, str, float]]:
    return [(i, str(item.product_name or ""), float(item.quantity or 0)) for i, item in enumerate(sale.items)]


def build_delivery_note(
    sale,
    shop=None,
    path: Path | None = None,
    selected: Optional[Iterable[int]] = None,
    style_id: str | None = None,
    font_size: int | None = None,
    overrides: Optional[dict] = None,
) -> Path:
    """Génère le bon de livraison des lignes ``selected`` (indices ; ``None`` = toutes)."""
    config.ensure_directories()
    shop = shop or settings_service.get_shop_info()
    c = _build_ctx(sale, shop, selected, style_id, overrides, font_size)
    if path is None:
        path = config.TICKET_DIR / f"BL_{c.number}_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    story, first, later, top, bottom = _LAYOUTS[c.style.layout](c)
    doc = BaseDocTemplate(str(path), pagesize=A4, leftMargin=MX, rightMargin=MX, topMargin=top, bottomMargin=bottom,
                          title=f"Bon de livraison {c.number}", author=str(shop.name or ""))
    f_first = Frame(MX, bottom, W - 2 * MX, H - top - bottom, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="first")
    later_top = 24 * mm if c.style.layout in ("bandeau", "marine", "cadres") else 42 * mm
    f_later = Frame(MX, bottom, W - 2 * MX, H - later_top - bottom, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="later")
    doc.addPageTemplates([PageTemplate(id="First", frames=[f_first], onPage=first, autoNextPageTemplate="Later"),
                          PageTemplate(id="Later", frames=[f_later], onPage=later)])
    doc.build(story)
    return path
