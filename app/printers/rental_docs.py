"""PDF de location : contrat (départ, retour prévu, caution, état) à faire signer par le client."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table

from app.printers.chantier_docs import _build, _grid, _header, _styles
from app.services import rental_service as rs, settings_service
from app.utils.helpers import format_money


def build_contract(rental_id: int, path: str | Path) -> Path:
    s = rs.summary(rental_id)
    shop = settings_service.get_shop_info()
    cur = shop.currency or "FCFA"
    base, h1, h2 = _styles()
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload
    from app.database.connection import session_scope
    from app.models.rental import Rental
    with session_scope() as session:
        r = session.execute(select(Rental).options(joinedload(Rental.lines)).where(Rental.id == rental_id)).unique().scalar_one()
        lines = [(l.label, l.quantity, float(l.rate_day)) for l in r.lines]
        id_doc, out_cond = r.id_document, r.out_condition
    story = _header(shop, f"CONTRAT DE LOCATION {s.number}", f"Départ le {s.start_date:%d/%m/%Y} — retour prévu le {s.due_date:%d/%m/%Y}", base, h1)
    story.append(Paragraph(f"<b>Client :</b> {s.client}   <b>Tél :</b> {s.phone or '—'}<br/><b>Pièce remise en garantie :</b> {id_doc or '—'}", base))
    story.append(Spacer(1, 4 * mm))
    rows = [["Matériel", "Qté", "Prix / jour", "Jours", "Montant"]]
    for label, qty, rate in lines:
        rows.append([label, str(qty), format_money(rate, cur), str(s.days_planned), format_money(rate * qty * s.days_planned, cur)])
    rows.append(["", "", "", "Loyer", format_money(s.base, cur)])
    story.append(_grid(rows, [78 * mm, 16 * mm, 32 * mm, 18 * mm, 32 * mm]))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(f"<b>Caution versée :</b> {format_money(s.deposit, cur)} &nbsp; <b>Loyer payé :</b> {format_money(s.paid, cur)} &nbsp; "
                           f"<b>Reste dû :</b> {format_money(s.balance, cur)}", base))
    story.append(Paragraph(f"<b>État au départ :</b> {out_cond or 'Bon état, complet.'}", base))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Conditions : le matériel doit être rendu complet et en bon état à la date prévue. Tout jour de retard est facturé "
                           "au tarif journalier. Les dégâts ou pièces manquantes sont retenus sur la caution.", base))
    story.append(Spacer(1, 14 * mm))
    sign = Table([["Le loueur", "Le client (lu et approuvé)"], ["\n\n\n", "\n\n\n"]], colWidths=[85 * mm, 85 * mm])
    story.append(sign)
    return _build(Path(path), story)
