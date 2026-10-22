"""Export Excel des rapports et des ventes via openpyxl."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.utils import get_column_letter
from openpyxl.styles import Alignment, Font, PatternFill

from app import config
from app.services import settings_service

_HEADER_FILL = PatternFill("solid", fgColor="2563EB")
_HEADER_FONT = Font(bold=True, color="FFFFFF")


def _style_header(worksheet, ncols: int) -> None:
    for col in range(1, ncols + 1):
        cell = worksheet.cell(row=1, column=col)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center")


def _autosize(worksheet) -> None:
    for column_cells in worksheet.columns:
        length = max((len(str(c.value or "")) for c in column_cells), default=10)
        letter = column_cells[0].column_letter
        worksheet.column_dimensions[letter].width = min(45, length + 4)


SECTIONS = [
    ("lines", "Lignes vendues"),
    ("daily", "Ventes par jour"),
    ("cashiers", "Par caissier"),
    ("client_debts", "Dettes clients"),
    ("supplier_debts", "Dettes fournisseurs"),
    ("expenses", "Dépenses"),
    ("cancelled", "Ventes annulées"),
    ("stock", "État du stock"),
    ("margins", "Marges par produit"),
    ("vat", "TVA par taux"),
]
PROFIT_SECTIONS = {"margins", "expenses"}

_MONEY = '#,##0.###'
_TOTAL_FONT = Font(bold=True)
_TOTAL_FILL = PatternFill("solid", fgColor="E2E8F0")


def _sheet(workbook, title, headers, rows, *, money_cols=(), total_cols=(), widths=None, first=False):
    """Crée un onglet : en-tête figé, filtres, formats monétaires, ligne de totaux (SUM)."""
    sheet = workbook.active if first else workbook.create_sheet()
    sheet.title = title[:31]
    sheet.append(list(headers))
    for row in rows:
        sheet.append(list(row))
    _style_header(sheet, len(headers))
    last = sheet.max_row
    for col in money_cols:
        for r in range(2, last + 1):
            sheet.cell(row=r, column=col).number_format = _MONEY
    if rows:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{last}"
        if total_cols:
            tr = last + 1
            sheet.cell(row=tr, column=1, value="TOTAL")
            for col in total_cols:
                letter = get_column_letter(col)
                cell = sheet.cell(row=tr, column=col, value=f"=SUBTOTAL(109,{letter}2:{letter}{last})")
                cell.number_format = _MONEY
            for col in range(1, len(headers) + 1):
                sheet.cell(row=tr, column=col).font = _TOTAL_FONT
                sheet.cell(row=tr, column=col).fill = _TOTAL_FILL
    _autosize(sheet)
    return sheet


def export_report_excel(
    report: dict,
    sales_rows=None,
    path: str | Path | None = None,
    include_profits: bool = True,
    details: dict | None = None,
    sections=None,
) -> Path:
    """Génère un classeur Excel complet (synthèse + onglets détaillés).

    ``sections`` : ensemble de clés de ``SECTIONS`` à inclure (``None`` = toutes).
    """
    config.ensure_directories()
    shop = settings_service.get_shop_info()
    currency = shop.currency or "FCFA"
    if details is None:
        from app.reports.report_data import collect_details

        details = collect_details(report["start"], report["end"])
    wanted = {k for k, _ in SECTIONS} if sections is None else set(sections)
    if not include_profits:
        wanted -= PROFIT_SECTIONS

    if path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = config.EXPORT_DIR / f"rapport_{stamp}.xlsx"
    path = Path(path)

    workbook = Workbook()

    summary = workbook.active
    summary.title = "Synthèse"
    summary.append([shop.name or "Rapport"])
    summary.append([f"Rapport du {report['start']:%d/%m/%Y} au {report['end']:%d/%m/%Y}"])
    summary.append([f"Généré le {datetime.now():%d/%m/%Y %H:%M}"])
    summary["A1"].font = Font(bold=True, size=16)
    summary["A2"].font = Font(bold=True, size=12)
    summary.append([])
    head = summary.max_row + 1
    summary.append(["Indicateur", f"Valeur ({currency})"])
    summary.append(["CA encaissé (ventes + règlements)", report["cash_revenue"]])
    summary.append(["dont règlements dettes clients", report["debt_repayments"]])
    summary.append(["Total ventes", report["total_sales"]])
    summary.append(["Nombre de ventes", report["sales_count"]])
    if report["sales_count"]:
        summary.append(["Panier moyen", round(report["total_sales"] / report["sales_count"], 3)])
    summary.append(["Crédit client non encaissé", report.get("credit_sales", 0)])
    summary.append(["Paiements dettes fournisseurs", report["supplier_debt_payments"]])
    summary.append(["Trésorerie période", report["treasury"]])
    if include_profits:
        summary.append(["Bénéfice brut", report["profit"]])
        summary.append(["Dépenses", report["expenses"]])
        summary.append(["Bénéfice net", report["net_profit"]])
    for col in (1, 2):
        c = summary.cell(row=head, column=col)
        c.fill, c.font, c.alignment = _HEADER_FILL, _HEADER_FONT, Alignment(horizontal="center")
    for r in range(head + 1, summary.max_row + 1):
        if r != head + 4:
            summary.cell(row=r, column=2).number_format = _MONEY
    _autosize(summary)
    summary.column_dimensions["A"].width = 40
    summary.column_dimensions["B"].width = 22

    _sheet(workbook, "Top produits", ["Produit", "Quantité", "Total ventes"], report["top_products"],
           money_cols=(3,), total_cols=(2, 3))
    pay_rows = list(report["payments"])
    if report.get("credit_sales", 0) > 0:
        pay_rows.append(("Crédit client (non encaissé)", report["credit_sales"]))
    _sheet(workbook, "Encaissements", ["Mode de paiement", "Montant"], pay_rows, money_cols=(2,), total_cols=(2,))

    if "daily" in wanted and details["daily"]:
        cols = ["Date", "Nb ventes", "Chiffre d'affaires", "Remises"] + (["Bénéfice"] if include_profits else [])
        rows = [r if include_profits else r[:4] for r in details["daily"]]
        sh = _sheet(workbook, "Ventes par jour", cols, rows, money_cols=(3, 4, 5), total_cols=tuple(range(2, len(cols) + 1)))
        if len(rows) > 1:
            chart = BarChart()
            chart.title = "Chiffre d'affaires par jour"
            chart.height, chart.width = 8, 18
            chart.add_data(Reference(sh, min_col=3, min_row=1, max_row=len(rows) + 1), titles_from_data=True)
            chart.set_categories(Reference(sh, min_col=1, min_row=2, max_row=len(rows) + 1))
            chart.legend = None
            sh.add_chart(chart, f"{get_column_letter(len(cols) + 2)}2")
        if details["hourly"]:
            _sheet(workbook, "Ventes par heure", ["Tranche", "Nb ventes", "Chiffre d'affaires"], details["hourly"],
                   money_cols=(3,), total_cols=(2, 3))
    if "cashiers" in wanted and details["cashiers"]:
        cols = ["Caissier", "Nb ventes", "Chiffre d'affaires", "Remises"] + (["Bénéfice"] if include_profits else []) + ["Annulations", "Montant annulé"]
        rows = [(r[0], r[1], r[2], r[3]) + ((r[4],) if include_profits else ()) + (r[5], r[6]) for r in details["cashiers"]]
        n = len(cols)
        _sheet(workbook, "Par caissier", cols, rows, money_cols=(3, 4, 5, n) if include_profits else (3, 4, n),
               total_cols=tuple(range(2, n + 1)))
    if "lines" in wanted and details["lines"]:
        cols = ["Date", "Ticket", "Produit", "Quantité", "Prix unitaire", "Total", "Caissier", "Client", "Paiement"]
        rows = [r[:9] for r in details["lines"]]
        mc = (5, 6)
        if include_profits:
            cols += ["Coût", "Marge"]
            rows = [r[:11] for r in details["lines"]]
            mc = (5, 6, 10, 11)
        _sheet(workbook, "Lignes vendues", cols, rows, money_cols=mc, total_cols=(6,) + ((10, 11) if include_profits else ()))
    if sales_rows:
        if include_profits:
            _sheet(workbook, "Ventes", ["Ticket", "Date", "Total ventes", "Bénéfice", "Statut"], sales_rows,
                   money_cols=(3, 4), total_cols=(3, 4))
        else:
            _sheet(workbook, "Ventes", ["Ticket", "Date", "Total ventes", "Statut"],
                   [(t, d, tot, st) for t, d, tot, _p, st in sales_rows], money_cols=(3,), total_cols=(3,))
    if "margins" in wanted and details["margins"]:
        _sheet(workbook, "Marges produits", ["Produit", "Quantité", "CA", "Coût", "Marge", "Marge %"], details["margins"],
               money_cols=(3, 4, 5), total_cols=(2, 3, 4, 5))
    if "client_debts" in wanted and details["client_debts"]:
        _sheet(workbook, "Dettes clients", ["Client", "Téléphone", "Date", "Échéance", "Montant initial", "Reste dû", "Ancienneté (j)", "Alerte", "Note"],
               details["client_debts"], money_cols=(5, 6), total_cols=(5, 6))
    if "supplier_debts" in wanted and details["supplier_debts"]:
        _sheet(workbook, "Dettes fournisseurs", ["Fournisseur", "Échéance", "Montant initial", "Reste dû", "Alerte", "Note"],
               details["supplier_debts"], money_cols=(3, 4), total_cols=(3, 4))
    if "expenses" in wanted and details["expenses"]:
        _sheet(workbook, "Dépenses", ["Date", "Catégorie", "Libellé", "Montant", "Notes"], details["expenses"],
               money_cols=(4,), total_cols=(4,))
    if "cancelled" in wanted and details["cancelled"]:
        _sheet(workbook, "Ventes annulées", ["Ticket", "Date", "Caissier", "Client", "Montant", "Motif"], details["cancelled"],
               money_cols=(5,), total_cols=(5,))
    if "stock" in wanted and details["stock"]:
        cols = ["Produit", "Catégorie", "Quantité", "Seuil", "Prix achat", "Prix vente", "Valeur achat", "Valeur vente", "Vendu (période)", "État"]
        rows = [r if include_profits else (r[0], r[1], r[2], r[3], None, r[5], None, r[7], r[8], r[9]) for r in details["stock"]]
        _sheet(workbook, "État du stock", cols, rows, money_cols=(5, 6, 7, 8), total_cols=(7, 8) if include_profits else (8,))
    if "vat" in wanted and details["vat"]:
        _sheet(workbook, "TVA par taux", ["Taux %", "Ventes TTC", "Hors taxe", "TVA incluse"], details["vat"],
               money_cols=(2, 3, 4), total_cols=(2, 3, 4))

    workbook.save(path)
    return path


def export_products_excel(products, path: str | Path | None = None) -> Path:
    """Exporte la liste des produits (utile pour l'inventaire)."""
    config.ensure_directories()
    if path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = config.EXPORT_DIR / f"produits_{stamp}.xlsx"
    path = Path(path)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Produits"
    sheet.append(
        ["Nom", "Catégorie", "Code-barres", "Référence", "Prix achat", "Prix vente", "Quantité", "Unité"]
    )
    for p in products:
        sheet.append(
            [
                p.name,
                p.category_name,
                p.barcode,
                p.reference,
                float(p.purchase_price),
                float(p.sale_price),
                float(p.quantity),
                p.unit_name,
            ]
        )
    _style_header(sheet, 8)
    _autosize(sheet)
    workbook.save(path)
    return path
