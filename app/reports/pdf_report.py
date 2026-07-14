"""Export PDF des rapports via ReportLab."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app import config
from app.services import settings_service
from app.utils.helpers import format_money


def _table(data, col_widths=None):
    table = Table(data, colWidths=col_widths, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def export_report_pdf(report: dict, path: str | Path | None = None) -> Path:
    """Génère un PDF récapitulatif pour la période du rapport."""
    config.ensure_directories()
    shop = settings_service.get_shop_info()
    currency = shop.currency or "FCFA"

    if path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = config.EXPORT_DIR / f"rapport_{stamp}.pdf"
    path = Path(path)

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm
    )
    story = []

    story.append(Paragraph(f"<b>{shop.name}</b>", styles["Title"]))
    story.append(
        Paragraph(
            f"Rapport du {report['start']:%d/%m/%Y} au {report['end']:%d/%m/%Y}",
            styles["Heading2"],
        )
    )
    story.append(Spacer(1, 8))

    summary = [
        ["Indicateur", "Valeur"],
        ["Chiffre d'affaires", format_money(report["revenue"], currency)],
        ["Nombre de ventes", str(report["sales_count"])],
        ["Bénéfice brut", format_money(report["profit"], currency)],
        ["Dépenses", format_money(report["expenses"], currency)],
        ["Bénéfice net", format_money(report["net_profit"], currency)],
    ]
    story.append(_table(summary, col_widths=[90 * mm, 70 * mm]))
    story.append(Spacer(1, 14))

    if report["top_products"]:
        story.append(Paragraph("<b>Produits les plus vendus</b>", styles["Heading3"]))
        rows = [["Produit", "Quantité", "CA"]]
        for name, qty, total in report["top_products"]:
            rows.append([name, f"{qty:g}", format_money(total, currency)])
        story.append(_table(rows, col_widths=[90 * mm, 30 * mm, 40 * mm]))
        story.append(Spacer(1, 14))

    if report["payments"]:
        story.append(Paragraph("<b>Encaissements par mode</b>", styles["Heading3"]))
        rows = [["Mode de paiement", "Montant"]]
        for method, amount in report["payments"]:
            rows.append([method, format_money(amount, currency)])
        story.append(_table(rows, col_widths=[90 * mm, 70 * mm]))
        story.append(Spacer(1, 14))

    if report["expense_breakdown"]:
        story.append(Paragraph("<b>Dépenses par catégorie</b>", styles["Heading3"]))
        rows = [["Catégorie", "Montant"]]
        for cat, amount in report["expense_breakdown"]:
            rows.append([cat, format_money(amount, currency)])
        story.append(_table(rows, col_widths=[90 * mm, 70 * mm]))

    story.append(Spacer(1, 20))
    story.append(
        Paragraph(
            f"<font size=8 color='#64748b'>Généré le {datetime.now():%d/%m/%Y %H:%M}</font>",
            styles["Normal"],
        )
    )
    doc.build(story)
    return path
