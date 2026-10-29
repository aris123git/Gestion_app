"""Bon d'enlèvement (PDF) : produits sélectionnés d'une vente.

Mise en page inspirée des bons d'enlèvement papier : titre + numéro, cadre
« Bon d'enlèvement / Date / Réf / BE N° », cadre client, tableau
PRODUIT / QUANTITÉ / U.M / P.U / P. TOTAL, totaux, mode de règlement, somme en
lettres, signatures (Le commercial / Le client) et pied de page légal.

Toutes les informations viennent des Paramètres (nom, adresse, RCCM, IFU,
compte…) : aucune ligne n'est imprimée si la donnée est vide.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app import config
from app.printers.invoice_a4 import HALF_H, amount_in_words, client_refs, get_font_size, get_format, FORMAT_HALF
from app.services import settings_service
from app.services.invoice_numbering import pickup_number
from app.utils.helpers import format_amount, format_money

SETTING_ENABLED = "bon_enabled"
SETTING_LEGAL = "bon_legal_text"
SETTING_ACOMPTE_RATE = "bon_acompte_rate"
SETTING_ACOMPTE_LABEL = "bon_acompte_label"
SETTING_COMMERCIAL = "bon_commercial"
SETTING_RCCM = "shop_rccm"
SETTING_IFU = "shop_ifu"
SETTING_BANK = "shop_bank_account"
SETTING_BANK_NAME = "shop_bank_name"

INK = colors.HexColor("#111827")
LINE = colors.HexColor("#111827")


def is_enabled() -> bool:
    return settings_service.get_setting(SETTING_ENABLED, "0").strip() == "1"


def _opt(key: str, overrides: Optional[dict] = None, default: str = "") -> str:
    if overrides is not None and key in overrides:
        return str(overrides[key] or "").strip()
    return settings_service.get_setting(key, default).strip()


def get_acompte(overrides: Optional[dict] = None) -> tuple[str, float]:
    label = _opt(SETTING_ACOMPTE_LABEL, overrides) or "Acompte"
    try:
        rate = float((_opt(SETTING_ACOMPTE_RATE, overrides, "0") or "0").replace(",", "."))
    except ValueError:
        rate = 0.0
    return label, max(0.0, rate)


def _units_by_product(sale) -> dict[int, str]:
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
            return {p.id: (p.unit.name if p.unit else "") for p in rows}
    except Exception:
        return {}


def selectable_lines(sale) -> list[tuple[int, str, float]]:
    """(index, désignation, quantité) de chaque ligne de la vente (pour la liste de choix)."""
    return [(i, str(item.product_name or ""), float(item.quantity or 0)) for i, item in enumerate(sale.items)]


def build_bon_enlevement(
    sale,
    shop=None,
    path: Path | None = None,
    selected: Optional[Iterable[int]] = None,
    fmt: str | None = None,
    font_size: int | None = None,
    overrides: Optional[dict] = None,
) -> Path:
    """Génère le bon d'enlèvement des lignes ``selected`` (indices ; ``None`` = toutes)."""
    config.ensure_directories()
    shop = shop or settings_service.get_shop_info()
    currency = shop.currency or "FCFA"
    items = list(sale.items)
    chosen = set(range(len(items))) if selected is None else {int(i) for i in selected}
    lines = [it for i, it in enumerate(items) if i in chosen]
    if not lines:
        raise ValueError("Aucun produit sélectionné pour le bon d'enlèvement.")

    half = (fmt or get_format()) == FORMAT_HALF
    page = (A4[0], HALF_H) if half else A4
    k = 0.7 if half else 1.0
    fs = max(7, int(round((font_size or get_font_size()) * (0.95 if half else 1.0))))
    number = pickup_number(sale)
    day = sale.date or datetime.now()

    if path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = config.TICKET_DIR / f"BE_{number}_{stamp}.pdf"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    legal = _opt(SETTING_LEGAL, overrides)
    rccm = _opt(SETTING_RCCM, overrides)
    ifu = _opt(SETTING_IFU, overrides)
    bank = _opt(SETTING_BANK, overrides)
    bank_name = _opt(SETTING_BANK_NAME, overrides)
    ac_label, ac_rate = get_acompte(overrides)

    base = ParagraphStyle("b", fontName="Helvetica", fontSize=fs, leading=fs * 1.3, textColor=INK)
    bold = ParagraphStyle("bb", parent=base, fontName="Helvetica-Bold")
    small = ParagraphStyle("s", parent=base, fontSize=max(6.5, fs - 2), leading=max(6.5, fs - 2) * 1.3)
    title_st = ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=fs + (5 if half else 8), leading=(fs + (5 if half else 8)) * 1.2, alignment=1)

    margin = 12 * mm * k
    foot_lines = []
    left_foot = [f"N°RCCM : {rccm}" if rccm else "", f"N°IFU : {ifu}" if ifu else "", f"BANQUE : {bank_name}" if bank_name else "", f"N°COMPTE : {bank}" if bank else ""]
    right_foot = [f"Email : {shop.email}" if shop.email else "", f"Tél : {shop.phone}" if shop.phone else "", f"Adresse : {shop.address}" if shop.address else ""]
    left_foot = [x for x in left_foot if x]
    right_foot = [x for x in right_foot if x]
    foot_lines = max(len(left_foot), len(right_foot))
    bottom = margin + (foot_lines * (fs - 1) * 1.35 + 6 * mm if foot_lines else 0)

    def on_page(canvas, doc):
        canvas.saveState()
        w, h = page
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(1)
        canvas.rect(6 * mm * k, 6 * mm * k, w - 12 * mm * k, h - 12 * mm * k)
        if foot_lines:
            y = margin + (foot_lines - 1) * (fs - 1) * 1.35
            canvas.setLineWidth(0.6)
            canvas.line(margin, y + (fs - 1) * 1.35 + 2 * mm, w - margin, y + (fs - 1) * 1.35 + 2 * mm)
            canvas.setFont("Helvetica-Bold", max(6.5, fs - 2))
            for i, text in enumerate(left_foot):
                canvas.drawString(margin, y - i * (fs - 1) * 1.35, text)
            for i, text in enumerate(right_foot):
                canvas.drawString(w / 2 + 6 * mm, y - i * (fs - 1) * 1.35, text)
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(path), pagesize=page, leftMargin=margin, rightMargin=margin, topMargin=10 * mm * k, bottomMargin=bottom,
        title=f"Bon d'enlèvement {number}", author=str(shop.name or ""),
    )
    frame_w = page[0] - 2 * margin
    story = []

    # En-tête : logo + nom du commerce
    head = [Paragraph(f"<b>{shop.name or ''}</b>", ParagraphStyle("h", parent=base, fontSize=fs + 4, leading=(fs + 4) * 1.2, alignment=1))]
    logo = Path(str(getattr(shop, "logo_path", "") or ""))
    if logo.is_file():
        try:
            story.append(Table([[Image(str(logo), width=16 * mm * k, height=16 * mm * k, kind="proportional"), head]], colWidths=[20 * mm * k, frame_w - 20 * mm * k],
                               style=[("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        except Exception:
            story.extend(head)
    else:
        story.extend(head)
    story.append(Spacer(1, 2 * mm * k))
    story.append(Paragraph(f"<u>BON D'ENLÈVEMENT</u> &nbsp;&nbsp;<font color='#1d4ed8'>N° {number}</font>", title_st))
    story.append(Spacer(1, 4 * mm * k))

    # Cadres : Bon d'enlèvement (gauche) / client (droite)
    left_rows = [[Paragraph("<b>Bon d'Enlèvement</b>", base)], [Paragraph(f"Date : <b>{day:%d/%m/%Y}</b>", base)],
                 [Paragraph(f"Réf : <b>{sale.ticket_number}</b>", base)], [Paragraph(f"BE N° <b>{number}</b>", base)]]
    left_box = Table(left_rows, colWidths=[frame_w * 0.42])
    left_box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.9, LINE), ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
                                  ("TOPPADDING", (0, 0), (-1, -1), 1 if half else 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 1 if half else 2)]))
    refs = client_refs(sale)
    client_id = getattr(sale, "client_id", None)
    right_rows = []
    if client_id:
        right_rows.append([Paragraph(f"<b>N° Client :</b> {int(client_id):05d}", base)])
    if refs.get("name") and (client_id or refs["name"] != "Client"):
        right_rows.append([Paragraph(f"<b>Nom Client :</b> {refs['name']}", base)])
    if refs.get("contact"):
        right_rows.append([Paragraph(f"<b>Contact :</b> {refs['contact']}", base)])
    if refs.get("address"):
        right_rows.append([Paragraph(f"<b>Adresse :</b> {refs['address']}", base)])
    if right_rows:
        right_box = Table(right_rows, colWidths=[frame_w * 0.52])
        right_box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.9, LINE), ("TOPPADDING", (0, 0), (-1, -1), 1 if half else 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 1 if half else 2)]))
    else:
        right_box = ""
    top = Table([[left_box, right_box]], colWidths=[frame_w * 0.46, frame_w * 0.54])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                             ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
    story += [top, Spacer(1, 5 * mm * k)]

    # Tableau produits
    units = _units_by_product(sale)
    head_row = ["PRODUIT", "QUANTITÉ", "U.M", "P.U", "P. TOTAL"]
    rows = [head_row]
    total = 0.0
    for it in lines:
        qty = float(it.quantity or 0)
        line_total = float(it.line_total or 0)
        total += line_total
        unit = units.get(getattr(it, "product_id", None) or -1, "")
        rows.append([Paragraph(str(it.product_name or ""), base), f"{qty:g}", unit.upper() if unit else "",
                     format_amount(float(it.unit_price or 0)), format_amount(line_total)])
    cw = [frame_w * 0.34, frame_w * 0.14, frame_w * 0.12, frame_w * 0.18, frame_w * 0.22]
    table = Table(rows, colWidths=cw, repeatRows=1)
    pad = max(1.2, fs * 0.2) if half else max(2.5, fs * 0.45)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), fs),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"), ("ALIGN", (3, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.8, LINE), ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
    ]))
    story += [table, Spacer(1, 4 * mm * k)]

    # Totaux + mention légale + somme en lettres
    acompte = round(total * ac_rate / 100, 3) if ac_rate > 0 else 0.0
    grand = round(total + acompte, 3)
    tot_rows = [["TOTAL", format_money(total, currency)]]
    if acompte > 0:
        tot_rows.append([f"{ac_label.upper()} {ac_rate:g}%", format_money(acompte, currency)])
        tot_rows.append(["TOTAL GÉNÉRAL", format_money(grand, currency)])
    totals = Table(tot_rows, colWidths=[frame_w * 0.20, frame_w * 0.26])
    totals.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.9, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.6, LINE), ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, -1), fs), ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("TOPPADDING", (0, 0), (-1, -1), 1.2 if half else 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2 if half else 2.5)]))
    left_cell = []
    if legal:
        left_cell.append(Paragraph(legal, small))
        left_cell.append(Spacer(1, 2 * mm))
    left_cell.append(Paragraph("<b>Arrêté le présent bon d'enlèvement à la somme de :</b>", base))
    left_cell.append(Paragraph(f"{amount_in_words(grand, currency)} ({format_money(grand, currency)})", base))
    methods = ", ".join(dict.fromkeys(str(p.method) for p in getattr(sale, "payments", []) if getattr(p, "method", "")))
    right_cell = [totals]
    if methods:
        right_cell += [Spacer(1, 1.5 * mm), Paragraph(f"<b>Mode de règlement :</b> {methods}", base)]
    bottom_block = Table([[left_cell, right_cell]], colWidths=[frame_w * 0.54, frame_w * 0.46])
    bottom_block.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, 0), 6 * mm * k), ("RIGHTPADDING", (1, 0), (1, 0), 0)]))
    # Signatures : le nom du commercial (Paramètres) et celui du client (l'entreprise)
    # remplacent les libellés génériques ; sans nom connu on garde le libellé.
    commercial = _opt(SETTING_COMMERCIAL, overrides)
    company = refs["name"] if (client_id and refs.get("name")) else ""
    sign = Table([[Paragraph(f"<b>{commercial or 'Le Commercial'}</b>", base), Paragraph(f"<b>{company or 'Le client'}</b>", ParagraphStyle("c", parent=base, alignment=2))]], colWidths=[frame_w / 2, frame_w / 2])
    sign.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(KeepTogether([bottom_block, Spacer(1, (5 if half else 8) * mm * k), sign]))

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return path


def in_print_all() -> bool:
    return settings_service.get_setting("bon_in_all", "1").strip() == "1"
