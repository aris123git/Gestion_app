"""Facture imprimable sur demi-feuille A4 (A4 coupé en deux).

Format page : 210 mm × 148,5 mm (largeur A4 × moitié de la hauteur).
Idéal pour une imprimante bureau classique avec du papier A4 pré-coupé.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app import config
from app.printers.thermal_printer import PrintResult
from app.services import settings_service
from app.utils.helpers import format_money, format_quantity

logger = logging.getLogger(__name__)

# Identifiant de format (réglages / dialogue ticket).
PAPER_HALF_A4 = "demi-A4"

# A4 = 210 × 297 mm → coupé en 2 horizontalement.
HALF_A4_SIZE = (210 * mm, 148.5 * mm)

# Largeur texte pour l'aperçu monospace du dialogue.
HALF_A4_WIDTH_CHARS = 72


def is_half_a4(paper: str) -> bool:
    key = (paper or "").strip().lower()
    return key in {PAPER_HALF_A4.lower(), "a4/2", "a4-2", "half-a4", "demi a4"}


def build_invoice_pdf(
    sale,
    shop=None,
    path: Path | None = None,
) -> Path:
    """Génère le PDF facture demi-A4 et retourne le chemin du fichier."""
    config.ensure_directories()
    shop = shop or settings_service.get_shop_info()
    currency = shop.currency or "FCFA"

    if path is None:
        path = config.TICKET_DIR / f"{sale.ticket_number}_demiA4.pdf"
        if path.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = config.TICKET_DIR / f"{sale.ticket_number}_demiA4_{stamp}.pdf"
    path = Path(path)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvoiceTitle",
        parent=styles["Heading1"],
        fontSize=14,
        spaceAfter=2,
        textColor=colors.HexColor("#0f172a"),
    )
    meta_style = ParagraphStyle(
        "InvoiceMeta",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#334155"),
        leading=11,
    )
    small = ParagraphStyle(
        "InvoiceSmall",
        parent=styles["Normal"],
        fontSize=7,
        textColor=colors.HexColor("#64748b"),
        leading=9,
    )

    doc = SimpleDocTemplate(
        str(path),
        pagesize=HALF_A4_SIZE,
        leftMargin=8 * mm,
        rightMargin=8 * mm,
        topMargin=6 * mm,
        bottomMargin=6 * mm,
    )
    story = []

    # En-tête commerce + logo éventuel.
    logo_path = Path(str(shop.logo_path or ""))
    logo_flowable = None
    if shop.logo_path and logo_path.exists():
        try:
            logo_flowable = Image(str(logo_path), width=16 * mm, height=16 * mm)
        except Exception:
            logger.debug("Logo facture demi-A4 ignoré.", exc_info=True)

    name_para = Paragraph(f"<b>{shop.name or 'Commerce'}</b>", title_style)
    addr_bits = []
    if shop.address:
        addr_bits.append(shop.address)
    if shop.phone:
        addr_bits.append(f"Tél. {shop.phone}")
    if shop.email:
        addr_bits.append(shop.email)
    addr_para = Paragraph(" · ".join(addr_bits), small) if addr_bits else Paragraph("", small)

    if logo_flowable is not None:
        left_cell = [[logo_flowable, [name_para, addr_para]]]
        left_table = Table(left_cell, colWidths=[18 * mm, 95 * mm])
        left_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        header_left = left_table
    else:
        header_left = [name_para, addr_para]

    moment = sale.date or datetime.now()
    right_lines = [
        "<b>FACTURE</b>",
        f"N° {sale.ticket_number}",
        f"{moment:%d/%m/%Y} {moment:%H:%M}",
        f"Caissier : {sale.cashier_name or '—'}",
    ]
    if getattr(sale, "client_id", None):
        right_lines.append(f"Client : {getattr(sale, 'client_name', '') or '—'}")
    header_right = Paragraph("<br/>".join(right_lines), meta_style)

    header = Table(
        [[header_left, header_right]],
        colWidths=[115 * mm, 70 * mm],
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(header)
    story.append(Spacer(1, 3 * mm))

    # Lignes produits.
    rows = [["Désignation", "Qté", "P.U.", "Montant"]]
    for item in sale.items:
        qty = format_quantity(item.quantity)
        unit_price = float(item.unit_price or 0)
        line_total = float(item.line_total or 0)
        expected = round(unit_price * float(item.quantity or 0), 2)
        if abs(expected - line_total) > 0.01:
            # Montant libre : pas de P.U. × qté classique.
            pu_txt = "—"
            qty_txt = "—"
        else:
            pu_txt = format_money(unit_price, currency)
            qty_txt = qty
        rows.append(
            [
                Paragraph(str(item.product_name or ""), small),
                qty_txt,
                pu_txt,
                format_money(line_total, currency),
            ]
        )

    items_table = Table(rows, colWidths=[95 * mm, 20 * mm, 35 * mm, 35 * mm])
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f8fafc")],
                ),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(items_table)
    story.append(Spacer(1, 3 * mm))

    # Totaux.
    totals = []
    totals.append(["Sous-total", format_money(sale.subtotal, currency)])
    if float(sale.discount or 0) > 0:
        totals.append(["Remise", format_money(sale.discount, currency)])
    vat_rate = settings_service.get_vat_rate()
    if vat_rate > 0:
        total_ttc = float(sale.total or 0)
        vat_amount = round(total_ttc * vat_rate / (100 + vat_rate), 2)
        total_ht = round(total_ttc - vat_amount, 2)
        totals.append(["Total HT", format_money(total_ht, currency)])
        totals.append([f"TVA {vat_rate:g}%", format_money(vat_amount, currency)])
        totals.append(["TOTAL TTC", format_money(total_ttc, currency)])
    else:
        totals.append(["TOTAL", format_money(sale.total, currency)])
    totals.append(["Reçu", format_money(sale.amount_received, currency)])
    totals.append(["Monnaie", format_money(sale.change_due, currency)])

    if sale.payments:
        for pay in sale.payments:
            totals.append([f"Paiement {pay.method}", format_money(pay.amount, currency)])

    totals_table = Table(totals, colWidths=[40 * mm, 40 * mm], hAlign="RIGHT")
    # Ligne au-dessus du TOTAL principal (avant Reçu / Monnaie / paiements).
    total_row = 0
    for index, row in enumerate(totals):
        if str(row[0]).upper().startswith("TOTAL"):
            total_row = index
            break
    style_cmds = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, total_row), (1, total_row), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LINEABOVE", (0, total_row), (-1, total_row), 0.6, colors.HexColor("#94a3b8")),
    ]
    totals_table.setStyle(TableStyle(style_cmds))
    story.append(totals_table)
    story.append(Spacer(1, 4 * mm))

    footer = shop.ticket_footer or "Merci pour votre visite."
    story.append(Paragraph(footer, small))
    story.append(
        Paragraph(
            "Format demi-A4 (210 × 148,5 mm) — papier A4 coupé en deux",
            small,
        )
    )

    doc.build(story)
    return path


def print_half_a4_invoice(
    sale,
    shop=None,
    printer_name: Optional[str] = None,
) -> PrintResult:
    """Génère le PDF demi-A4 puis l'envoie à l'imprimante bureau (non RAW)."""
    shop = shop or settings_service.get_shop_info()
    try:
        pdf_path = build_invoice_pdf(sale, shop=shop)
    except Exception as exc:
        logger.exception("Génération PDF demi-A4 impossible.")
        return PrintResult(False, Path(), f"Impossible de générer la facture PDF : {exc}")

    printer_name = (
        printer_name
        if printer_name is not None
        else settings_service.get_setting("printer_name", "")
    ).strip()
    from app.printers.thermal_printer import resolve_printer_name

    printer_name, printer_warning = resolve_printer_name(printer_name)

    if sys.platform.startswith("win"):
        result = _print_pdf_windows(pdf_path, printer_name)
    else:
        result = _print_pdf_posix(pdf_path, printer_name)
    if printer_warning:
        result.message = (
            f"{printer_warning}\n{result.message}".strip()
            if result.message
            else printer_warning
        )
    result.file_path = pdf_path
    return result


def _print_pdf_windows(pdf_path: Path, printer_name: str) -> PrintResult:  # pragma: no cover
    try:
        import win32api
        import win32print
    except Exception as exc:
        return PrintResult(
            False,
            pdf_path,
            f"Impression PDF indisponible (pywin32) : {exc}. "
            f"Ouvrez le fichier manuellement : {pdf_path}",
        )

    target = printer_name or win32print.GetDefaultPrinter()
    if not target:
        return PrintResult(
            False,
            pdf_path,
            f"Aucune imprimante configurée. PDF enregistré : {pdf_path}",
        )

    # Réutilise le pré-contrôle offline du module thermique.
    from app.printers import thermal_printer as tp

    preflight = tp._windows_printer_preflight(target)
    if preflight is not None:
        preflight.file_path = pdf_path
        preflight.message += f" PDF enregistré : {pdf_path}"
        return preflight

    try:
        # « printto » permet de cibler une imprimante précise.
        win32api.ShellExecute(
            0,
            "printto",
            str(pdf_path),
            f'"{target}"',
            ".",
            0,
        )
    except Exception:
        try:
            win32api.ShellExecute(0, "print", str(pdf_path), None, ".", 0)
        except Exception as exc:
            return PrintResult(
                False,
                pdf_path,
                f"Échec d'impression PDF : {exc}. Fichier : {pdf_path}",
            )
        return PrintResult(
            True,
            pdf_path,
            f"Facture demi-A4 envoyée à l'imprimante par défaut.\nPDF : {pdf_path}",
        )

    return PrintResult(
        True,
        pdf_path,
        f"Facture demi-A4 envoyée à « {target} ».\nPDF : {pdf_path}",
    )


def _print_pdf_posix(pdf_path: Path, printer_name: str) -> PrintResult:
    command = ["lp"]
    if printer_name and not ("/" in printer_name or printer_name.startswith("\\")):
        command += ["-d", printer_name]
    command.append(str(pdf_path))
    try:
        proc = subprocess.run(
            command, capture_output=True, timeout=30, check=False
        )
    except FileNotFoundError:
        return PrintResult(
            False,
            pdf_path,
            f"CUPS/lp introuvable. Ouvrez le PDF manuellement : {pdf_path}",
        )
    except Exception as exc:
        return PrintResult(False, pdf_path, f"Échec d'impression PDF : {exc}")
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip() or "erreur inconnue"
        return PrintResult(
            False,
            pdf_path,
            f"Échec d'impression PDF : {detail}. Fichier : {pdf_path}",
        )
    where = printer_name or "imprimante par défaut"
    return PrintResult(
        True,
        pdf_path,
        f"Facture demi-A4 envoyée à « {where} ».\nPDF : {pdf_path}",
    )
