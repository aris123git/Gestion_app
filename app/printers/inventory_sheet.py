"""Feuille d'inventaire A4 : tous les produits, une case « compté » à remplir à la main."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services import settings_service


def build_inventory_sheet(rows: Sequence[tuple[str, str, str]], path: Path, show_expected: bool = False) -> Path:
    """rows : (produit, unité, stock attendu). Le stock attendu n'est imprimé que si `show_expected`."""
    shop = settings_service.get_shop_info()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title="Feuille d'inventaire")
    title = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15, spaceAfter=2)
    small = ParagraphStyle("s", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#475569"))
    cell = ParagraphStyle("c", fontName="Helvetica", fontSize=9.5, leading=11)
    story = [Paragraph("Feuille d'inventaire", title),
             Paragraph(f"{shop.name or ''} · {datetime.now():%d/%m/%Y}   —   Compté par : ______________________", small), Spacer(1, 6 * mm)]
    head = ["Produit", "Unité"] + (["Stock attendu"] if show_expected else []) + ["Quantité comptée"]
    data = [head]
    for name, unit, expected in rows:
        data.append([Paragraph(name, cell), unit] + ([expected] if show_expected else []) + [""])
    widths = [78 * mm, 20 * mm] + ([28 * mm] if show_expected else []) + [None]
    free = 182 * mm - sum(w for w in widths if w)
    widths = [w if w else free for w in widths]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9.5), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94a3b8")), ("FONT", (1, 1), (-1, -1), "Helvetica", 9.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 1), (-1, -1), 5), ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("ALIGN", (-2 if show_expected else -1, 1), (-1, -1), "RIGHT"),
    ]))
    story.append(table)
    doc.build(story)
    return path
