"""PDF des chantiers : devis / marché, reçu de paiement, rapport de chantier (client, banque, appel d'offres)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app import config
from app.database.connection import session_scope
from app.models.chantier import STATUS_LABELS, Chantier, ChantierPayment
from app.services import chantier_service as cs, settings_service
from app.utils.helpers import format_money
from app.utils.amount_words import amount_in_words

INK = colors.HexColor("#111827")
ACCENT = colors.HexColor("#1e3a8a")


def _styles():
    base = ParagraphStyle("b", fontName="Helvetica", fontSize=9.5, leading=12.5, textColor=INK)
    return base, ParagraphStyle("h", parent=base, fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=ACCENT, spaceAfter=4), \
        ParagraphStyle("s", parent=base, fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=ACCENT, spaceBefore=8, spaceAfter=3)


def _grid(rows, widths, header=True):
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    cmds = [("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#9ca3af")), ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        cmds += [("BACKGROUND", (0, 0), (-1, 0), ACCENT), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    table.setStyle(TableStyle(cmds))
    return table


def _load(chantier_id: int) -> Chantier:
    with session_scope() as session:
        chantier = session.execute(select(Chantier).options(
            joinedload(Chantier.lines), joinedload(Chantier.expenses), joinedload(Chantier.payments), joinedload(Chantier.addenda),
            joinedload(Chantier.milestones), joinedload(Chantier.lots)).where(Chantier.id == chantier_id)).unique().scalar_one()
        session.expunge_all()
        return chantier


def _header(shop, title: str, sub: str, base, h1):
    return [Paragraph(f"<b>{shop.name or ''}</b><br/>{shop.address or ''}  {('Tél : ' + shop.phone) if shop.phone else ''}", base), Spacer(1, 6 * mm),
            Paragraph(title, h1), Paragraph(sub, base), Spacer(1, 4 * mm)]


def _build(path: Path, story) -> Path:
    config.ensure_directories()
    path = Path(path)
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm).build(story)
    return path


def build_quote(chantier_id: int, path: Path | None = None) -> Path:
    """Devis (ou marché) à remettre au client : lignes, avenants, total."""
    shop, c = settings_service.get_shop_info(), _load(chantier_id)
    cur = shop.currency or "FCFA"
    base, h1, h2 = _styles()
    is_quote = c.status in ("devis", "accepte", "refuse")
    story = _header(shop, f"{'DEVIS' if is_quote else 'MARCHÉ'} N° {c.number}", f"{c.name}<br/>Client : {c.client_label or '—'}   ·   Lieu : {c.location or '—'}   ·   Date : {datetime.now():%d/%m/%Y}", base, h1)
    rows = [["Désignation", "Qté", "Unité", "P.U", "Total"]] + [[Paragraph(l.label, base), f"{float(l.quantity):g}", l.unit, f"{float(l.unit_price):,.0f}".replace(",", " "), f"{l.total:,.0f}".replace(",", " ")] for l in c.lines]
    total_lines = sum(l.total for l in c.lines)
    if c.lines:
        story += [_grid(rows, [88 * mm, 18 * mm, 20 * mm, 24 * mm, 26 * mm]), Spacer(1, 3 * mm)]
    amount = float(c.amount or 0) or total_lines
    summary = [["Montant du " + ("devis" if is_quote else "marché"), format_money(amount, cur)]]
    for a in c.addenda:
        summary.append([f"Avenant n°{a.number} — {a.label}", format_money(float(a.amount), cur)])
    if c.addenda:
        summary.append(["TOTAL", format_money(amount + sum(float(a.amount) for a in c.addenda), cur)])
    story += [_grid(summary, [130 * mm, 46 * mm], header=False)]
    story += [Spacer(1, 3 * mm), Paragraph(f"<b>Arrêté {'le présent devis' if is_quote else 'le présent marché'} à la somme de :</b> "
                                           f"{amount_in_words(amount + sum(float(a.amount) for a in c.addenda), cur)}", base)]
    if c.milestones:
        story += [Paragraph("Échéancier de paiement", h2), _grid([["Échéance", "%", "Montant"]] + [[m.label, f"{float(m.pct):g} %", format_money(amount * float(m.pct) / 100, cur)] for m in c.milestones], [100 * mm, 26 * mm, 50 * mm])]
    story += [Spacer(1, 18 * mm), Table([["Le client (lu et approuvé)", "L'entreprise"], ["", ""]], colWidths=[88 * mm, 88 * mm], rowHeights=[6 * mm, 22 * mm],
                                         style=TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("BOX", (0, 1), (0, 1), 0.5, colors.grey), ("BOX", (1, 1), (1, 1), 0.5, colors.grey)]))]
    return _build(path or config.TICKET_DIR / f"{c.number}_{'devis' if is_quote else 'marche'}.pdf", story)


def build_invoice(chantier_id: int, path: Path | None = None) -> Path:
    """Facture du client pour tout le marché : lignes du devis + avenants, acomptes déjà encaissés, reste à payer."""
    from app.printers import invoice_a4 as ia

    shop, c = settings_service.get_shop_info(), _load(chantier_id)
    cur = shop.currency or "FCFA"
    base, h1, h2 = _styles()
    number = f"FAC-{c.number}"
    client = c.client_label or "—"
    story = _header(shop, f"FACTURE N° {number}", f"Date : {datetime.now():%d/%m/%Y}<br/>Client : <b>{client}</b><br/>Objet : {c.name}" + (f" — {c.location}" if c.location else ""), base, h1)
    rows = [["Désignation", "Qté", "Unité", "P.U", "Total"]]
    lines_total = 0.0
    for l in c.lines:
        rows.append([Paragraph(l.label, base), f"{float(l.quantity):g}", l.unit, f"{float(l.unit_price):,.0f}".replace(",", " "), f"{l.total:,.0f}".replace(",", " ")])
        lines_total += l.total
    amount = float(c.amount or 0)
    if not c.lines or abs(amount - lines_total) > 0.5:
        # montant convenu différent des lignes (ou pas de lignes) : ligne d'ajustement pour que la facture colle au marché
        rows.append([Paragraph(c.name if not c.lines else "Ajustement du marché", base), "1", "", "", f"{amount - lines_total:,.0f}".replace(",", " ")])
    for a in c.addenda:
        rows.append([Paragraph(f"Avenant n°{a.number} — {a.label}", base), "1", "", "", f"{float(a.amount):,.0f}".replace(",", " ")])
    total = amount + sum(float(a.amount) for a in c.addenda)
    received = sum(float(p.amount) for p in c.payments)
    story += [_grid(rows, [88 * mm, 18 * mm, 20 * mm, 24 * mm, 26 * mm]), Spacer(1, 3 * mm)]
    sums = [["TOTAL", format_money(total, cur)]]
    if ia.show_legal() and float(shop.vat_rate or 0) > 0:        # TVA seulement si l'option est cochée (Paramètres → Facture)
        vat = round(total * float(shop.vat_rate) / (100 + float(shop.vat_rate)), 0)
        sums.append([f"dont TVA {float(shop.vat_rate):g} %", format_money(vat, cur)])
    for p in sorted(c.payments, key=lambda p: p.date):
        sums.append([f"Acompte reçu le {p.date:%d/%m/%Y} ({p.kind}, {p.method})", "− " + format_money(float(p.amount), cur)])
    sums.append(["RESTE À PAYER", format_money(max(0.0, total - received), cur)])
    story += [_grid(sums, [130 * mm, 46 * mm], header=False)]
    story += [Spacer(1, 3 * mm), Paragraph(f"<b>Arrêtée la présente facture à la somme de :</b> {amount_in_words(total, cur)}", base)]
    extra = "  ·  ".join(x for x in (ia.legal_text(), ia.bank_text()) if x)
    if extra:
        story += [Spacer(1, 6 * mm), Paragraph(extra, base)]
    story += [Spacer(1, 16 * mm), Table([["Signature et cachet"], [""]], colWidths=[70 * mm], rowHeights=[6 * mm, 22 * mm], style=TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("BOX", (0, 1), (0, 1), 0.5, colors.grey)]))]
    return _build(path or config.TICKET_DIR / f"{number}.pdf", story)


def build_receipt(payment_id: int, path: Path | None = None) -> Path:
    """Reçu imprimable pour un encaissement."""
    shop = settings_service.get_shop_info()
    cur = shop.currency or "FCFA"
    with session_scope() as session:
        payment = session.execute(select(ChantierPayment).options(joinedload(ChantierPayment.chantier)).where(ChantierPayment.id == payment_id)).unique().scalar_one()
        c = payment.chantier
        number, date, kind, amount, method, ref = payment.number, payment.date, payment.kind, float(payment.amount), payment.method, payment.reference
        cname, cnum, client = c.name, c.number, c.client_label
        contract = float(c.amount or 0) + sum(float(a.amount) for a in c.addenda)
        received = sum(float(p.amount) for p in c.payments if (p.date, p.id) <= (date, payment_id))
    base, h1, _ = _styles()
    story = _header(shop, f"REÇU N° {number}", f"Date : {date:%d/%m/%Y}", base, h1)
    story += [_grid([["Reçu de", client or "—"], ["Chantier", f"{cnum} — {cname}"], ["Nature", kind], ["Mode de paiement", method + (f" ({ref})" if ref else "")],
                     ["MONTANT REÇU", format_money(amount, cur)], ["Total encaissé à ce jour", format_money(received, cur)], ["Reste à payer sur le marché", format_money(max(0.0, contract - received), cur)]],
                    [60 * mm, 116 * mm], header=False), Spacer(1, 20 * mm),
              Table([["Signature et cachet"], [""]], colWidths=[70 * mm], rowHeights=[6 * mm, 22 * mm], style=TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("BOX", (0, 1), (0, 1), 0.5, colors.grey)]))]
    return _build(path or config.TICKET_DIR / f"{number}_recu.pdf", story)


def build_report(chantier_id: int, path: Path | None = None) -> Path:
    """Rapport de chantier : situation financière, avancement, dépenses par catégorie, encaissements."""
    shop, c, s = settings_service.get_shop_info(), _load(chantier_id), cs.summary(chantier_id)
    cur = shop.currency or "FCFA"
    base, h1, h2 = _styles()
    story = _header(shop, f"RAPPORT DE CHANTIER — {c.number}", f"{c.name}<br/>Client : {c.client_label or '—'}   ·   Lieu : {c.location or '—'}   ·   Statut : {STATUS_LABELS.get(c.status, c.status)}   ·   Édité le {datetime.now():%d/%m/%Y}", base, h1)
    story += [_grid([["Montant du marché (avenants inclus)", format_money(s.contract, cur)], ["Encaissé", format_money(s.received, cur)], ["Reste à encaisser", format_money(s.remaining_to_receive, cur)],
                     ["Dépensé", format_money(s.spent, cur)], ["Marge", f"{format_money(s.margin, cur)} ({s.margin_pct:g} %)"], ["Avancement", f"{s.progress_pct:g} %"]], [100 * mm, 76 * mm], header=False)]
    if s.by_category:
        story += [Paragraph("Dépenses par catégorie", h2), _grid([["Catégorie", "Montant"]] + [[k, format_money(v, cur)] for k, v in sorted(s.by_category.items())], [100 * mm, 76 * mm])]
    if c.payments:
        story += [Paragraph("Encaissements", h2), _grid([["Date", "Nature", "Mode", "Montant"]] + [[f"{p.date:%d/%m/%Y}", p.kind, p.method, format_money(float(p.amount), cur)] for p in sorted(c.payments, key=lambda p: p.date)], [30 * mm, 50 * mm, 46 * mm, 50 * mm])]
    if c.addenda:
        story += [Paragraph("Avenants", h2), _grid([["N°", "Date", "Objet", "Montant"]] + [[a.number, f"{a.date:%d/%m/%Y}", Paragraph(a.label, base), format_money(float(a.amount), cur)] for a in c.addenda], [14 * mm, 28 * mm, 90 * mm, 44 * mm])]
    for alert in s.alerts:
        story += [Spacer(1, 2 * mm), Paragraph(f"<b>⚠ {alert}</b>", base)]
    return _build(path or config.TICKET_DIR / f"{c.number}_rapport.pdf", story)
