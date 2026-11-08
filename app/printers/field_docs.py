"""Bon de sortie d'une tournée : la liste de ce qui est remis au vendeur ambulant (A4 ou ticket 80 mm)."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Paragraph, Spacer, Table

from app.printers.chantier_docs import _build, _grid, _header, _styles
from app.services import field_sales_service as fs, settings_service
from app.utils.helpers import format_money


def _data(run_id: int):
    from sqlalchemy import select
    from app.database.connection import session_scope
    from app.models.field_sales import FieldRun, FieldSeller

    with session_scope() as session:
        run = session.get(FieldRun, run_id)
        if run is None:
            raise ValueError("Sortie introuvable.")
        seller = session.get(FieldSeller, run.seller_id)
        head = dict(number=run.number, out_at=run.out_at, seller=seller.name if seller else "", phone=seller.phone if seller else "", notes=run.notes or "")
    lines = [(l.product_name, float(l.qty_out), float(l.unit_price)) for l in fs.get_run_lines(run_id)]
    return head, lines


def build_out_ticket(run_id: int, path: str | Path, fmt: str = "a4") -> Path:
    """``fmt`` : « a4 » (bon signé) ou « ticket » (rouleau 80 mm)."""
    head, lines = _data(run_id)
    shop = settings_service.get_shop_info()
    cur = shop.currency or "FCFA"
    if fmt == "ticket":
        return _build_roll(Path(path), head, lines, shop, cur)
    base, h1, h2 = _styles()
    story = _header(shop, f"BON DE SORTIE {head['number']}", f"Remis le {head['out_at']:%d/%m/%Y à %H:%M}", base, h1)
    story.append(Paragraph(f"<b>Vendeur :</b> {head['seller']}" + (f" &nbsp; <b>Tél :</b> {head['phone']}" if head["phone"] else ""), base))
    story.append(Spacer(1, 4 * mm))
    rows = [["Produit", "Quantité sortie", "Prix de vente", "Valeur"]]
    total = 0.0
    for name, qty, price in lines:
        total += qty * price
        rows.append([name, f"{qty:g}", format_money(price, cur), format_money(qty * price, cur)])
    rows.append(["", "", "Valeur totale", format_money(total, cur)])
    story.append(_grid(rows, [84 * mm, 32 * mm, 32 * mm, 32 * mm]))
    if head["notes"]:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(f"<b>Note :</b> {head['notes']}", base))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Le vendeur reconnaît avoir reçu la marchandise ci-dessus. Il rapporte le soir les invendus et l'argent des ventes.", base))
    story.append(Spacer(1, 12 * mm))
    sign = Table([["Le responsable (signature)", "Le vendeur (reçu, signature)"], ["\n\n\n\n", "\n\n\n\n"]], colWidths=[85 * mm, 85 * mm])
    sign.setStyle([("BOX", (0, 0), (0, 1), 0.5, colors.grey), ("BOX", (1, 0), (1, 1), 0.5, colors.grey), ("FONTSIZE", (0, 0), (-1, 0), 8)])
    story.append(sign)
    return _build(Path(path), story)


def _build_roll(path: Path, head: dict, lines: list, shop, cur: str) -> Path:
    w = 80 * mm
    pad = 4 * mm
    lh = 4.2 * mm
    rows: list[tuple[str, str, bool]] = []  # (texte gauche, droite, gras)
    rows.append(((shop.name or "").upper(), "", True))
    rows.append(("BON DE SORTIE", head["number"], True))
    rows.append((f"{head['out_at']:%d/%m/%Y %H:%M}", "", False))
    rows.append((f"Vendeur : {head['seller']}", "", False))
    rows.append(("-" * 38, "", False))
    total = 0.0
    for name, qty, price in lines:
        total += qty * price
        rows.append((name[:34], "", True))
        rows.append((f"  {qty:g} x {format_money(price, cur)}", format_money(qty * price, cur), False))
    rows.append(("-" * 38, "", False))
    rows.append(("VALEUR TOTALE", format_money(total, cur), True))
    if head["notes"]:
        rows.append((f"Note : {head['notes'][:30]}", "", False))
    rows.append(("", "", False))
    rows.append(("Signature du vendeur :", "", False))
    height = pad * 2 + lh * (len(rows) + 5)
    c = rl_canvas.Canvas(str(path), pagesize=(w, height))
    y = height - pad - lh
    for left, right, bold in rows:
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 8.5)
        c.drawString(pad, y, left)
        if right:
            c.drawRightString(w - pad, y, right)
        y -= lh
    c.line(pad, y - 8 * mm, w - pad, y - 8 * mm)
    c.save()
    return path
