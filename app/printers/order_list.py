"""Liste de commande A4 (produits à réapprovisionner), par fournisseur."""

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


def build_order_list(rows: Sequence[tuple[str, str, str, str]], path: Path, supplier: str = "") -> Path:
    """rows : (produit, unité, stock actuel, quantité à commander)."""
    shop = settings_service.get_shop_info()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title="Liste de commande")
    title = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15, spaceAfter=2)
    small = ParagraphStyle("s", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#475569"))
    cell = ParagraphStyle("c", fontName="Helvetica", fontSize=9.5, leading=11)
    sub = f"{shop.name or ''} · {datetime.now():%d/%m/%Y}" + (f" · Fournisseur : {supplier}" if supplier else "")
    story = [Paragraph("Liste de commande", title), Paragraph(sub, small), Spacer(1, 6 * mm)]
    data = [["Produit", "Unité", "Stock actuel", "À commander"]]
    for name, unit, stock, qty in rows:
        data.append([Paragraph(name, cell), unit, stock, qty])
    table = Table(data, colWidths=[84 * mm, 24 * mm, 36 * mm, 38 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9.5), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94a3b8")), ("FONT", (1, 1), (-1, -1), "Helvetica", 9.5),
        ("FONT", (3, 1), (3, -1), "Helvetica-Bold", 10), ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 1), (-1, -1), 5), ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
    ]))
    story.append(table)
    doc.build(story)
    return path
