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


def _footer(canvas, doc, shop_name):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(15 * mm, 10 * mm, f"{shop_name} — généré le {datetime.now():%d/%m/%Y %H:%M}")
    canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _chart(daily, currency):
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing

    rows = daily[-31:]
    drawing = Drawing(180 * mm, 55 * mm)
    chart = VerticalBarChart()
    chart.x, chart.y, chart.width, chart.height = 22 * mm, 10 * mm, 150 * mm, 40 * mm
    chart.data = [[float(r[2]) for r in rows]]
    chart.categoryAxis.categoryNames = [r[0][:5] for r in rows]
    chart.categoryAxis.labels.fontSize = 6
    chart.categoryAxis.labels.angle = 45 if len(rows) > 8 else 0
    chart.categoryAxis.labels.dy = -6
    chart.valueAxis.labels.fontSize = 6
    chart.valueAxis.valueMin = 0
    chart.bars[0].fillColor = colors.HexColor("#2563eb")
    drawing.add(chart)
    return drawing


def export_report_pdf(
    report: dict,
    path: str | Path | None = None,
    include_profits: bool = True,
    details: dict | None = None,
    sections=None,
) -> Path:
    """Génère un PDF complet pour la période du rapport.

    ``sections`` : clés à inclure (``None`` = toutes). Les lignes vendues
    (potentiellement très nombreuses) ne figurent que dans l'export Excel.
    """
    config.ensure_directories()
    shop = settings_service.get_shop_info()
    currency = shop.currency or "FCFA"
    if details is None:
        from app.reports.report_data import collect_details

        details = collect_details(report["start"], report["end"])
    all_keys = {"daily", "cashiers", "client_debts", "supplier_debts", "expenses", "cancelled", "stock", "margins", "vat"}
    wanted = all_keys if sections is None else set(sections) & all_keys
    if not include_profits:
        wanted -= {"margins", "expenses"}

    if path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = config.EXPORT_DIR / f"rapport_{stamp}.pdf"
    path = Path(path)

    styles = getSampleStyleSheet()
    shop_name = str(shop.name or "")
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, topMargin=15 * mm, bottomMargin=18 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm, title=f"Rapport {shop_name}", author=shop_name,
    )
    styles["Heading3"].keepWithNext = 1
    story = []
    money = lambda v: format_money(v, currency)  # noqa: E731

    def section(title, header, rows, widths, right_from=1, limit=None, note=None):
        if not rows:
            return
        shown = rows[:limit] if limit else rows
        story.append(Paragraph(f"<b>{title}</b>", styles["Heading3"]))
        table = _table([header] + [list(r) for r in shown], col_widths=widths)
        table.setStyle(TableStyle([("ALIGN", (right_from, 0), (-1, -1), "RIGHT"), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
        story.append(table)
        if limit and len(rows) > limit:
            story.append(Paragraph(f"<font size=8 color='#64748b'>… {len(rows) - limit} ligne(s) supplémentaire(s) dans l'export Excel.</font>", styles["Normal"]))
        if note:
            story.append(Paragraph(f"<font size=8 color='#64748b'>{note}</font>", styles["Normal"]))
        story.append(Spacer(1, 12))

    logo = Path(str(getattr(shop, "logo_path", "") or ""))
    title_block = [Paragraph(f"<b>{shop_name}</b>", styles["Title"])]
    if shop.address or shop.phone:
        title_block.append(Paragraph(f"<font size=9 color='#475569'>{shop.address or ''} {('· ' + shop.phone) if shop.phone else ''}</font>", styles["Normal"]))
    if logo.is_file():
        try:
            from reportlab.platypus import Image

            head = Table([[Image(str(logo), width=22 * mm, height=22 * mm, kind="proportional"), title_block]], colWidths=[26 * mm, 150 * mm])
            head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
            story.append(head)
        except Exception:
            story.extend(title_block)
    else:
        story.extend(title_block)
    story.append(Paragraph(f"Rapport du {report['start']:%d/%m/%Y} au {report['end']:%d/%m/%Y}", styles["Heading2"]))
    story.append(Spacer(1, 6))

    summary = [
        ["Indicateur", "Valeur"],
        ["CA encaissé (ventes + règlements)", money(report["cash_revenue"])],
        ["dont règlements dettes clients", money(report["debt_repayments"])],
        ["Total ventes", money(report["total_sales"])],
        ["Nombre de ventes", str(report["sales_count"])],
    ]
    if report["sales_count"]:
        summary.append(["Panier moyen", money(report["total_sales"] / report["sales_count"])])
    summary += [
        ["Crédit client non encaissé", money(report.get("credit_sales", 0))],
        ["Paiements dettes fournisseurs", money(report["supplier_debt_payments"])],
        ["Trésorerie période", money(report["treasury"])],
    ]
    if include_profits:
        summary += [["Bénéfice brut", money(report["profit"])], ["Dépenses", money(report["expenses"])], ["Bénéfice net", money(report["net_profit"])]]
    story.append(_table(summary, col_widths=[100 * mm, 70 * mm]))
    story.append(Spacer(1, 14))

    if "daily" in wanted and details["daily"]:
        if len(details["daily"]) > 1:
            story.append(Paragraph("<b>Évolution du chiffre d'affaires</b>", styles["Heading3"]))
            story.append(_chart(details["daily"], currency))
        cols = ["Date", "Ventes", "Chiffre d'affaires", "Remises"] + (["Bénéfice"] if include_profits else [])
        section("Ventes par jour", cols, [(r[0], r[1], money(r[2]), money(r[3])) + ((money(r[4]),) if include_profits else ()) for r in details["daily"]],
                [30 * mm, 22 * mm, 45 * mm, 35 * mm] + ([40 * mm] if include_profits else []), limit=45)
    section("Produits les plus vendus", ["Produit", "Quantité", "Total ventes"],
            [(n, f"{q:g}", money(t)) for n, q, t in report["top_products"]], [90 * mm, 30 * mm, 50 * mm])
    section("Encaissements par mode", ["Mode de paiement", "Montant"], [(m, money(a)) for m, a in report["payments"]], [100 * mm, 70 * mm])
    if "cashiers" in wanted:
        cols = ["Caissier", "Ventes", "CA", "Remises"] + (["Bénéfice"] if include_profits else []) + ["Annul."]
        section("Par caissier", cols, [(r[0], r[1], money(r[2]), money(r[3])) + ((money(r[4]),) if include_profits else ()) + (r[5],) for r in details["cashiers"]],
                [40 * mm, 18 * mm, 38 * mm, 30 * mm] + ([34 * mm] if include_profits else []) + [18 * mm])
    if "margins" in wanted:
        section("Marges par produit (top 15)", ["Produit", "Qté", "CA", "Marge", "Marge %"],
                [(r[0], f"{r[1]:g}", money(r[2]), money(r[4]), f"{r[5]:.1f} %") for r in details["margins"]],
                [65 * mm, 20 * mm, 38 * mm, 38 * mm, 20 * mm], limit=15)
    if "vat" in wanted:
        section("TVA par taux (incluse dans les prix)", ["Taux", "Ventes TTC", "Hors taxe", "TVA"],
                [(f"{r[0]:g} %", money(r[1]), money(r[2]), money(r[3])) for r in details["vat"]], [30 * mm, 45 * mm, 45 * mm, 45 * mm])
    if "client_debts" in wanted:
        total = sum(r[5] for r in details["client_debts"])
        section("Dettes clients en cours", ["Client", "Échéance", "Reste dû", "Ancienneté", "Alerte"],
                [(r[0], r[3], money(r[5]), f"{r[6]} j" if r[6] != "" else "", r[7]) for r in details["client_debts"]],
                [60 * mm, 28 * mm, 40 * mm, 22 * mm, 22 * mm], limit=30, note=f"Total dû par les clients : {money(total)}")
    if "supplier_debts" in wanted:
        total = sum(r[3] for r in details["supplier_debts"])
        section("Dettes fournisseurs en cours", ["Fournisseur", "Échéance", "Reste dû", "Alerte"],
                [(r[0], r[1], money(r[3]), r[4]) for r in details["supplier_debts"]], [70 * mm, 30 * mm, 45 * mm, 25 * mm], limit=30,
                note=f"Total dû aux fournisseurs : {money(total)}")
    if "expenses" in wanted:
        section("Dépenses par catégorie", ["Catégorie", "Montant"], [(c, money(a)) for c, a in report["expense_breakdown"]], [100 * mm, 70 * mm])
        section("Détail des dépenses", ["Date", "Catégorie", "Libellé", "Montant"],
                [(r[0], r[1], r[2], money(r[3])) for r in details["expenses"]], [25 * mm, 40 * mm, 65 * mm, 40 * mm], limit=40)
    if "cancelled" in wanted:
        section("Ventes annulées", ["Ticket", "Date", "Caissier", "Montant", "Motif"],
                [(r[0], r[1], r[2], money(r[4]), r[5]) for r in details["cancelled"]], [28 * mm, 32 * mm, 30 * mm, 30 * mm, 50 * mm], limit=30)
    if "stock" in wanted:
        alerts = [r for r in details["stock"] if r[9] in ("Rupture", "Stock bas")]
        value = sum(r[6] for r in details["stock"])
        section("Stock à surveiller", ["Produit", "Quantité", "Seuil", "État"], [(r[0], f"{r[2]:g}", f"{r[3]:g}", r[9]) for r in alerts],
                [80 * mm, 30 * mm, 30 * mm, 30 * mm], limit=30,
                note=(f"Valeur du stock (prix d'achat) : {money(value)}" if include_profits else None))

    footer = lambda c, d: _footer(c, d, shop_name)  # noqa: E731
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return path
