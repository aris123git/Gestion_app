"""Exports Excel / PDF de la comptabilité simplifiée."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, TableStyle

from app import config
from app.reports.excel_report import _sheet
from app.reports.pdf_report import _footer, _table
from app.services import accounting_service as acc
from app.services import settings_service
from app.utils.helpers import format_money


def export_accounting_excel(data: dict, path: str | Path | None = None) -> Path:
    config.ensure_directories()
    shop = settings_service.get_shop_info()
    if path is None:
        path = config.EXPORT_DIR / f"comptabilite_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    path = Path(path)
    wb = Workbook()
    rows = [(label, amount) for label, amount, _bold in acc.result_rows(data)]
    sh = _sheet(wb, "Résultat", ["Libellé", f"Montant ({shop.currency or 'FCFA'})"], rows, money_cols=(2,), first=True)
    for r, (_l, _a, bold) in enumerate(acc.result_rows(data), start=2):
        if bold:
            sh.cell(row=r, column=1).font = Font(bold=True)
            sh.cell(row=r, column=2).font = Font(bold=True)
    sh.column_dimensions["A"].width = 48
    sh.column_dimensions["B"].width = 22
    sh.append([])
    sh.append([f"Période : {data['start']:%d/%m/%Y} au {data['end']:%d/%m/%Y}"])
    _sheet(wb, "Journal", acc.JOURNAL_HEADERS, data["journal"], money_cols=(7, 8, 9), total_cols=(7, 8, 9))
    _sheet(wb, "TVA", ["Taux %", "Ventes TTC", "Hors taxe", "TVA collectée"], data["vat"], money_cols=(2, 3, 4), total_cols=(2, 3, 4))
    cash = data["cash"]
    rows = [("ENTRÉES", None)] + list(cash["inflows"]) + [("Total entrées", cash["total_in"]), ("SORTIES", None)] + list(cash["outflows"]) + [
        ("Total sorties", cash["total_out"]), ("SOLDE DE LA PÉRIODE", cash["balance"]), ("Achats non réglés (à crédit)", cash["purchases_on_credit"])]
    tr = _sheet(wb, "Trésorerie", ["Libellé", "Montant"], rows, money_cols=(2,))
    tr.column_dimensions["A"].width = 40
    wb.save(path)
    return path


def export_accounting_pdf(data: dict, path: str | Path | None = None, journal_limit: int = 150) -> Path:
    config.ensure_directories()
    shop = settings_service.get_shop_info()
    currency = shop.currency or "FCFA"
    if path is None:
        path = config.EXPORT_DIR / f"comptabilite_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    path = Path(path)
    styles = getSampleStyleSheet()
    styles["Heading3"].keepWithNext = 1
    name = str(shop.name or "")
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), topMargin=15 * mm, bottomMargin=18 * mm,
                            leftMargin=15 * mm, rightMargin=15 * mm, title=f"Comptabilité {name}", author=name)
    money = lambda v: format_money(v, currency)  # noqa: E731
    story = [Paragraph(f"<b>{name}</b>", styles["Title"]),
             Paragraph(f"Comptabilité simplifiée du {data['start']:%d/%m/%Y} au {data['end']:%d/%m/%Y}", styles["Heading2"]), Spacer(1, 6)]

    story.append(Paragraph("<b>Compte de résultat</b>", styles["Heading3"]))
    rr = acc.result_rows(data)
    t = _table([["Libellé", "Montant"]] + [[l, money(a)] for l, a, _b in rr], col_widths=[150 * mm, 60 * mm])
    cmds = [("ALIGN", (1, 0), (1, -1), "RIGHT")]
    for i, (_l, _a, bold) in enumerate(rr, start=1):
        if bold:
            cmds.append(("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"))
    t.setStyle(TableStyle(cmds))
    story += [t, Spacer(1, 12)]

    if data["vat"]:
        story.append(Paragraph("<b>TVA collectée (incluse dans les prix)</b>", styles["Heading3"]))
        t = _table([["Taux", "Ventes TTC", "Hors taxe", "TVA"]] + [[f"{r[0]:g} %", money(r[1]), money(r[2]), money(r[3])] for r in data["vat"]],
                   col_widths=[30 * mm, 55 * mm, 55 * mm, 55 * mm])
        t.setStyle(TableStyle([("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
        story += [t, Spacer(1, 12)]

    cash = data["cash"]
    story.append(Paragraph("<b>Trésorerie de la période</b>", styles["Heading3"]))
    rows = [["Libellé", "Montant"]] + [[m, money(a)] for m, a in cash["inflows"]] + [["Total entrées", money(cash["total_in"])]]
    rows += [[m, "- " + money(a)] for m, a in cash["outflows"]] + [["Total sorties", "- " + money(cash["total_out"])], ["SOLDE DE LA PÉRIODE", money(cash["balance"])]]
    t = _table(rows, col_widths=[150 * mm, 60 * mm])
    t.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONTNAME", (0, len(rows) - 1), (-1, len(rows) - 1), "Helvetica-Bold")]))
    story += [t, Spacer(1, 12)]

    journal = data["journal"]
    if journal:
        story.append(Paragraph("<b>Journal des opérations</b>", styles["Heading3"]))
        body = [[r[0], r[1], r[2], r[3], r[5], money(r[6]) if r[6] else "", money(r[7]) if r[7] else "", money(r[8]) if r[8] else ""] for r in journal[:journal_limit]]
        t = _table([["Date", "Type", "Pièce", "Tiers", "Mode", "Entrée", "Sortie", "À crédit"]] + body,
                   col_widths=[32 * mm, 38 * mm, 36 * mm, 42 * mm, 24 * mm, 30 * mm, 30 * mm, 30 * mm])
        t.setStyle(TableStyle([("ALIGN", (5, 0), (-1, -1), "RIGHT"), ("FONTSIZE", (0, 0), (-1, -1), 7.5)]))
        story.append(t)
        if len(journal) > journal_limit:
            story.append(Paragraph(f"<font size=8 color='#64748b'>… {len(journal) - journal_limit} opération(s) supplémentaire(s) dans l'export Excel.</font>", styles["Normal"]))

    footer = lambda c, d: _footer(c, d, name)  # noqa: E731
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return path
