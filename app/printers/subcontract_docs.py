"""PDF de sous-traitance : contrat avec situation des paiements."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table

from app.printers.chantier_docs import _build, _grid, _header, _styles
from app.services import settings_service, subcontract_service as ss
from app.utils.helpers import format_money


def build_contract(subcontract_id: int, path: str | Path) -> Path:
    s = ss.summary(subcontract_id)
    shop = settings_service.get_shop_info()
    cur = shop.currency or "FCFA"
    base, h1, h2 = _styles()
    story = _header(shop, f"CONTRAT DE SOUS-TRAITANCE {s.number}", f"Chantier : {s.chantier}", base, h1)
    sub = next((x for x in ss.list_subcontractors(True) if x.name == s.subcontractor), None)
    contact = f" — {sub.trade}" if sub and sub.trade else ""
    story.append(Paragraph(f"<b>Sous-traitant :</b> {s.subcontractor}{contact}<br/><b>Tél :</b> {(sub.phone if sub else '') or '—'} &nbsp; "
                           f"<b>IFU / RCCM :</b> {(sub.tax_id if sub else '') or '—'}", base))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(f"<b>Travail confié :</b> {s.label}", base))
    end = f"{s.end_planned:%d/%m/%Y}" if s.end_planned else "—"
    story.append(Paragraph(f"<b>Forfait :</b> {format_money(s.amount, cur)} &nbsp; <b>Retenue de garantie :</b> {s.retention_pct:g} % "
                           f"({format_money(s.retention, cur)}) &nbsp; <b>Fin prévue :</b> {end}", base))
    story.append(Spacer(1, 4 * mm))
    rows = [["Date", "Type", "Référence", "Montant"]]
    for p in ss.list_payments(subcontract_id):
        rows.append([f"{p.date:%d/%m/%Y}", p.kind, p.reference or "", format_money(float(p.amount), cur)])
    if len(rows) == 1:
        rows.append(["", "Aucun paiement", "", ""])
    story.append(_grid(rows, [30 * mm, 55 * mm, 45 * mm, 40 * mm]))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(f"<b>Déjà versé :</b> {format_money(s.paid, cur)} &nbsp; <b>Reste à payer :</b> {format_money(s.payable_now, cur)} &nbsp; "
                           f"<b>Retenue détenue :</b> {format_money(s.retention_held, cur)}", base))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("La retenue de garantie est libérée à la réception des travaux, après levée des réserves éventuelles.", base))
    story.append(Spacer(1, 14 * mm))
    sign = Table([["L'entreprise (nom, signature, cachet)", "Le sous-traitant (lu et approuvé, signature)"], ["\n\n\n\n", "\n\n\n\n"]], colWidths=[85 * mm, 85 * mm])
    sign.setStyle([("BOX", (0, 0), (0, 1), 0.5, colors.grey), ("BOX", (1, 0), (1, 1), 0.5, colors.grey), ("FONTSIZE", (0, 0), (-1, 0), 8)])
    story.append(sign)
    return _build(Path(path), story)
