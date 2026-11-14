"""PDF du module Gaz : bandeau des jours d'un voyage (plusieurs pages), cahier du jour, relevé d'un grossiste, pertes."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer

from app.printers.chantier_docs import _build, _grid, _header, _styles
from app.services import gas_service as gs, settings_service

W = A4[0] - 32 * mm


def _m(v) -> str:
    return f"{round(float(v or 0)):,}".replace(",", " ")


def _shop():
    return settings_service.get_shop_info()


def build_trip_bandeau(trip_id: int, path: str | Path) -> Path:
    """Voyage complet : en-tête, bilan par produit, puis les étapes jour par jour (le tableau passe sur autant de pages que nécessaire)."""
    base, h1, h2 = _styles()
    trip = gs.get_trip(trip_id)
    story = _header(_shop(), f"Voyage {escape(trip.number)} — {escape(trip.truck or 'camion')}",
                    f"Chauffeur : {escape(trip.driver or '—')} · Chargé à : {escape(trip.source)} · Départ : {trip.started_at:%d/%m/%Y}"
                    + (f" · Retour : {trip.ended_at:%d/%m/%Y}" if trip.ended_at else " · en cours"), base, h1)
    story.append(Paragraph("Bilan du camion", h2))
    rows = [["Produit", "Chargé", "Détaillants", "Grossistes", "Pertes", "Restant"]]
    for r in gs.trip_summary(trip_id):
        rows.append([r["name"], r["loaded"], r["sold"], r["delivered"], r["lost"], r["remaining"] if not r["transferred"] else f"{r['remaining']} (reste → dépôt: {r['transferred']})"])
    story.append(_grid(rows, [60 * mm, 20 * mm, 24 * mm, 24 * mm, 18 * mm, W - 146 * mm]))
    story.append(Paragraph("Étapes jour par jour", h2))
    rows = [["Jour", "Étape", "Détail", "Montant"]]
    for d in gs.trip_days(trip_id):
        first = True
        for st in d["steps"]:
            detail = ", ".join(f"{n} × {q}" for n, q in st["lines"].items()) + (f" — {'; '.join(st['reasons'])}" if st["reasons"] else "")
            rows.append([f"{d['date']:%d/%m/%Y}" if first else "", st["who"], Paragraph(escape(detail), base), _m(st["amount"]) if st["amount"] else ""])
            first = False
        rows.append(["", "Total du jour", "", _m(d["total"])])
    story.append(_grid(rows, [24 * mm, 40 * mm, W - 24 * mm - 40 * mm - 28 * mm, 28 * mm]))
    back = gs.empties_returned(trip_id)
    if back:
        story.append(Paragraph("Vides remises à la source", h2))
        story.append(_grid([["Bouteille", "Proposées", "Remises"]] + [[f"{b['size_kg']:g} kg".replace(".", ","), b["proposed"], b["handed"]] for b in back],
                           [50 * mm, 30 * mm, 30 * mm]))
    return _build(Path(path), story)


def build_day_sheet(day: date, path: str | Path, trip_id: int | None = None, part: str = "both") -> Path:
    """Cahier du jour. ``part`` : « detaillants », « grossistes » ou « both » (les deux, chacun sur sa page)."""
    from datetime import datetime, timedelta

    base, h1, h2 = _styles()
    sub = f"{day:%d/%m/%Y}" + (f" — camion {gs.get_trip(trip_id).label}" if trip_id else " — dépôt")
    story = []
    sheet = gs.day_sheet(day, trip_id)
    if part in ("both", "detaillants"):
        story += _header(_shop(), "Cahier du jour — Détaillants", escape(sub), base, h1)
        rows = [["Produit", "S.I", "Entrée", "S.T", "Vente", "P.U", "Montant", "S.F"]]
        for r in sheet:
            rows.append([r["name"], r["si"], r["entry"], r["st"], r["sold"], _m(r["unit_price"]), _m(r["amount"]), r["sf"]])
        rows.append(["TOTAL", "", "", "", sum(r["sold"] for r in sheet), "", _m(gs.day_total(day, trip_id)), ""])
        story.append(_grid(rows, [48 * mm, 16 * mm, 18 * mm, 16 * mm, 18 * mm, 22 * mm, 28 * mm, W - 166 * mm]))
        extra = [(r["name"], r["delivered"], r["lost"]) for r in sheet if r["delivered"] or r["lost"]]
        if extra:
            story.append(Paragraph("Sorties du jour qui ne sont pas des ventes aux détaillants (déjà déduites du S.F)", h2))
            story.append(_grid([["Produit", "Livré aux grossistes", "Pertes"]] + [list(e) for e in extra], [60 * mm, 40 * mm, 30 * mm]))
    if part == "both":
        story.append(PageBreak())
    if part in ("both", "grossistes"):
        story += _header(_shop(), "Cahier du jour — Grossistes (feuille « Entrée »)", escape(sub), base, h1)
        lines = [r for r in sheet]
        names = [r["name"] for r in lines]
        ids = [r["line_id"] for r in lines]
        deliveries = gs.deliveries_of_day(day, trip_id=trip_id)
        end = datetime(day.year, day.month, day.day) + timedelta(days=1)
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle

        hs = ParagraphStyle("gh", parent=base, fontName="Helvetica-Bold", fontSize=6.5, leading=8, textColor=colors.white, alignment=1)

        def _h(txt: str):
            return Paragraph(escape(txt).replace(" Recharge", "<br/>Rech.").replace(" Consigné", "<br/>Cons.").replace(" Complet", "<br/>Compl."), hs)

        head = ["Grossiste"] + [_h(n) for n in names] + [_h("Vides"), "Total", _h("Reste à payer")]
        rows = [head]
        tot_lines = {i: 0 for i in ids}
        for d in deliveries:
            acc = gs.wholesaler_account(d["wholesaler_id"], until=end)
            for i in ids:
                tot_lines[i] += d["lines"].get(i, 0)
            rows.append([d["wholesaler"]] + [d["lines"].get(i, "") for i in ids] + [d["empties_back"], _m(d["total"]), _m(acc.balance)])
        rows.append(["TOTAL"] + [tot_lines[i] or "" for i in ids] + [sum(d["empties_back"] for d in deliveries), _m(sum(d["total"] for d in deliveries)), ""])
        n = len(ids)
        story.append(_grid(rows, [36 * mm] + [(W - 36 * mm - 56 * mm) / max(n, 1)] * n + [14 * mm, 20 * mm, 22 * mm]))
        if not deliveries:
            story.append(Paragraph("Aucune livraison aux grossistes ce jour.", base))
    return _build(Path(path), story)


def build_wholesaler_statement(wholesaler_id: int, path: str | Path) -> Path:
    base, h1, h2 = _styles()
    acc = gs.wholesaler_account(wholesaler_id)
    story = _header(_shop(), f"Relevé du grossiste — {escape(acc.name)}", f"Édité le {date.today():%d/%m/%Y}", base, h1)
    story.append(Paragraph(escape(acc.statement) + ".", base))
    story.append(Spacer(1, 3 * mm))
    story.append(_grid([["Livré", "Vides rendues", "Total livré", "Payé", "Reste à payer", "Vides à rendre"],
                        [acc.delivered, acc.empties_back, _m(acc.amount_due), _m(acc.paid), _m(acc.balance), acc.bottles_owed]], [W / 6] * 6))
    story.append(Paragraph("Détail", h2))
    rows = [["Date", "Opération", "Détail", "Dû", "Payé", "Reste", "Vides à rendre"]]
    for e in gs.wholesaler_history(wholesaler_id):
        rows.append([f"{e['date']:%d/%m/%Y}", "Livraison" if e["kind"] == "livraison" else "Paiement", Paragraph(escape(e["detail"]), base),
                     _m(e["due"]) if e["due"] else "", _m(e["paid"]) if e["paid"] else "", _m(e["balance"]), e["bottles_owed"]])
    story.append(_grid(rows, [22 * mm, 22 * mm, W - 22 * mm - 22 * mm - 90 * mm, 22 * mm, 22 * mm, 24 * mm, 20 * mm]))
    return _build(Path(path), story)


def build_losses(start: date, end: date, path: str | Path) -> Path:
    base, h1, h2 = _styles()
    story = _header(_shop(), "Pertes de bouteilles", f"Du {start:%d/%m/%Y} au {end:%d/%m/%Y} — supportées par l'entreprise, rien n'est facturé", base, h1)
    rows = [["Date", "Produit", "Bouteilles", "Motif"]]
    items = gs.losses(start, end)
    for l in items:
        rows.append([f"{l['date']:%d/%m/%Y}", l["line"], l["qty"], Paragraph(escape(l["reason"]), base)])
    rows.append(["", "Total", sum(l["qty"] for l in items), ""])
    story.append(_grid(rows, [24 * mm, 50 * mm, 26 * mm, W - 100 * mm]))
    return _build(Path(path), story)
