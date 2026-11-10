"""Facture proforma au format commercial courant : bandeau d'en-tête, « Doit », objet, tableau, total en lettres, responsable."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, Spacer, Table, TableStyle
from PIL import Image as PILImage

from app import config
from app.printers import invoice_a4 as ia
from app.printers.chantier_docs import _build
from app.services import proforma_service as ps, settings_service
from app.utils.helpers import format_money

INK = colors.HexColor("#111827")
PAGE_W = A4[0] - 32 * mm


def _num(v: float) -> str:
    return f"{float(v):,.0f}".replace(",", " ").replace(" ", " ")


def _qty(line: dict) -> str:
    q = f"{line['quantity']:g}"
    return f"{q}{line['unit']}" if line["unit"] and len(line["unit"]) <= 3 else (f"{q} {line['unit']}" if line["unit"] else q)


def _banner():
    path = Path(settings_service.get_setting(ps.SETTING_BANNER, "").strip() or "/nonexistent")
    if not path.is_file():
        return None
    try:
        with PILImage.open(path) as im:
            w, h = im.size
        height = min(PAGE_W * h / w, 45 * mm)
        return Image(str(path), width=height * w / h, height=height, hAlign="CENTER")
    except Exception:  # noqa: BLE001 - image illisible : on retombe sur l'en-tête texte
        return None


def build_proforma_pdf(proforma_id: int, path: str | Path | None = None) -> Path:
    d = ps.get(proforma_id)
    shop = settings_service.get_shop_info()
    cur = shop.currency or "FCFA"
    get = settings_service.get_setting
    base = ParagraphStyle("pb", fontName="Helvetica", fontSize=10, leading=13.5, textColor=INK)
    bold = ParagraphStyle("pbb", parent=base, fontName="Helvetica-Bold")
    center = ParagraphStyle("pc", parent=bold, fontSize=12.5, leading=16, alignment=TA_CENTER)
    right = ParagraphStyle("pr", parent=base, alignment=TA_RIGHT)
    small = ParagraphStyle("ps", parent=base, fontSize=8, leading=10, textColor=colors.HexColor("#374151"), alignment=TA_CENTER)

    story = []
    banner = _banner()
    if banner is not None:
        story.append(banner)
    else:
        head = ParagraphStyle("ph", parent=bold, fontSize=20, leading=24, alignment=TA_CENTER, textColor=colors.HexColor("#1e3a8a"))
        story.append(Paragraph(escape(shop.name or ""), head))
        for line in (get(ps.SETTING_TAGLINE, ""), get(ps.SETTING_HEADER_EXTRA, ""), shop.address or "", f"Tél. {shop.phone}" if shop.phone else ""):
            if (line or "").strip():
                story.append(Paragraph(escape(line.strip()), ParagraphStyle("pl", parent=bold, fontSize=9.5, alignment=TA_CENTER)))
    story.append(Table([[""]], colWidths=[PAGE_W], rowHeights=[1], style=TableStyle([("LINEABOVE", (0, 0), (-1, 0), 1.2, colors.HexColor("#be123c"))])))
    city = get(ps.SETTING_CITY, "").strip()
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(f"{escape(city) + ' le ' if city else 'Le '}{d['date']:%d/%m/%Y}", ParagraphStyle("pd", parent=base, fontSize=9, alignment=TA_RIGHT)))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"<u>FACTURE PROFORMA N°{escape(d['number'])}</u>", center))
    story.append(Spacer(1, 5 * mm))

    who = [f"<u><b>Doit :</b></u> {escape(d['client_name'])}"]
    for label, key in (("Tél", "client_phone"), ("Email", "client_email"), ("IFU", "client_ifu"), ("RCCM", "client_rccm"),
                       ("Régime fiscal", "client_regime"), ("Division fiscale", "client_division"), ("Adresse", "client_address")):
        if (d[key] or "").strip():
            who.append(f"{label} : {escape(d[key].strip())}")
    story.append(Paragraph("<br/>".join(who), base))
    if (d["subject"] or "").strip():
        story += [Spacer(1, 3 * mm), Paragraph(f"<u><b>Objet :</b></u> {escape(d['subject'].strip())}", base)]
    story.append(Spacer(1, 4 * mm))

    cdt = any((l["packaging"] or "").strip() for l in d["lines"])
    head = ["Désignation"] + (["CDT"] if cdt else []) + ["Quant.", "Prix Unit.", "Prix total"]
    widths = ([68, 22, 26, 28, 32] if cdt else [86, 26, 32, 36])
    widths = [w * mm for w in widths]
    widths[0] += PAGE_W - sum(widths)
    rows = [head]
    for l in d["lines"]:
        rows.append([Paragraph(escape(l["label"]), base)] + ([l["packaging"]] if cdt else []) + [_qty(l), _num(l["unit_price"]), _num(l["quantity"] * l["unit_price"])])
    t = d["totals"]
    n = len(head)
    foot = []
    if t.tax > 0:
        foot += [["MONTANT HT"] + [""] * (n - 2) + [_num(t.subtotal)], [f"{t.tax_label.upper()} {t.tax_rate:g} %"] + [""] * (n - 2) + [_num(t.tax)],
                 ["MONTANT TTC"] + [""] * (n - 2) + [_num(t.total)]]
    else:
        foot += [["TOTAL GENERAL"] + [""] * (n - 2) + [_num(t.total)]]
    table = Table(rows + foot, colWidths=widths, repeatRows=1)
    first_foot = len(rows)
    cmds = [("BOX", (0, 0), (-1, -1), 1.3, INK), ("LINEBELOW", (0, 0), (-1, 0), 1.3, INK), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"), ("ALIGN", (1, 1), (-1, -1), "CENTER"), ("ALIGN", (-1, 1), (-1, -1), "RIGHT"), ("ALIGN", (-2, 1), (-2, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("FONTSIZE", (0, 0), (-1, -1), 9.5), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEABOVE", (0, first_foot), (-1, first_foot), 1.3, INK), ("FONTNAME", (0, first_foot), (-1, -1), "Helvetica-Bold"), ("ALIGN", (0, first_foot), (0, -1), "LEFT")]
    for i in range(first_foot, first_foot + len(foot)):
        cmds.append(("SPAN", (0, i), (n - 2, i)))
    for c in range(1, n):
        cmds.append(("LINEBEFORE", (c, 0), (c, first_foot - 1), 1.0, INK))
    cmds.append(("LINEBEFORE", (n - 1, first_foot), (n - 1, -1), 1.0, INK))
    table.setStyle(TableStyle(cmds))
    story += [table, Spacer(1, 3 * mm)]
    story.append(Paragraph(f"Arrêtée la présente facture proforma à la somme de : <u><b>{escape(ia.number_to_words_fr(int(round(t.total))).upper())} "
                           f"({_num(t.total)}) {escape('FRANCS CFA' if cur.upper() in ('FCFA', 'CFA', 'XOF', 'F CFA') else cur)}</b></u>", base))
    if (d["notes"] or "").strip():
        story += [Spacer(1, 3 * mm), Paragraph(escape(d["notes"].strip()).replace("\n", "<br/>"), base)]
    story += [Spacer(1, 8 * mm), Paragraph("<u><b>Le Responsable</b></u>", right), Spacer(1, 22 * mm)]
    if (d["responsible"] or "").strip():
        story.append(Paragraph(f"<b>{escape(d['responsible'].strip())}</b>" + (f"<br/><b>Tél : {escape(d['responsible_phone'].strip())}</b>" if (d["responsible_phone"] or "").strip() else ""), right))
    extra = "  ·  ".join(x for x in (ia.legal_text(), ia.bank_text()) if x)
    if extra:
        story += [Spacer(1, 10 * mm), Paragraph(escape(extra), small)]
    out = Path(path) if path else config.TICKET_DIR / f"proforma_{d['number'].replace('/', '-')}.pdf"
    return _build(out, story)
