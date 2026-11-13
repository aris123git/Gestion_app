"""Factures proforma : numérotation annuelle (062/2026), lignes, totaux, réglages (en-tête image, responsable)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select

from app.database.connection import session_scope
from app.models.proforma import STATUS_OPEN, STATUSES, Proforma, ProformaLine
from app.services import settings_service

SETTING_ENABLED = "proforma_enabled"
SETTING_BANNER = "proforma_banner_path"        # image d'en-tête (bandeau pleine largeur)
SETTING_RESPONSIBLE = "proforma_responsible"
SETTING_RESPONSIBLE_PHONE = "proforma_responsible_phone"
SETTING_CITY = "proforma_city"
SETTING_TAGLINE = "proforma_tagline"           # ex. « Vente de la viande – Poisson – Poulet »
SETTING_HEADER_EXTRA = "proforma_header_extra"  # ex. secteur, téléphones


def enabled() -> bool:
    return settings_service.get_setting(SETTING_ENABLED, "0") == "1"


def set_enabled(value: bool) -> None:
    settings_service.set_setting(SETTING_ENABLED, "1" if value else "0")


@dataclass
class LineInput:
    label: str
    quantity: float = 1
    unit: str = ""
    unit_price: float = 0
    packaging: str = ""


@dataclass
class Totals:
    subtotal: float
    tax_label: str
    tax_rate: float
    tax: float
    total: float


def compute_totals(lines, tax_label: str = "", tax_rate: float = 0) -> Totals:
    sub = round(sum(float(l.quantity or 0) * float(l.unit_price or 0) for l in lines), 2)
    rate = float(tax_rate or 0)
    tax = round(sub * rate / 100, 2) if rate > 0 else 0.0
    return Totals(sub, (tax_label or "Taxe").strip() if rate > 0 else "", rate, tax, round(sub + tax, 2))


def _next_number(session, year: int) -> tuple[int, str]:
    seq = int(session.scalar(select(func.max(Proforma.seq)).where(Proforma.year == year)) or 0) + 1
    return seq, f"{seq:03d}/{year}"


FIELDS = ("client_id", "client_name", "client_phone", "client_email", "client_ifu", "client_rccm", "client_regime",
          "client_division", "client_address", "subject", "tax_label", "tax_rate", "responsible", "responsible_phone", "notes")


def save(lines: list[LineInput], *, proforma_id: Optional[int] = None, date: Optional[datetime] = None, **fields) -> int:
    lines = [l for l in lines if (l.label or "").strip()]
    if not lines:
        raise ValueError("Ajoutez au moins une ligne.")
    if not (fields.get("client_name") or "").strip():
        raise ValueError("Indiquez le client.")
    for l in lines:
        if float(l.quantity or 0) <= 0:
            raise ValueError(f"Quantité invalide pour « {l.label} ».")
        if float(l.unit_price or 0) < 0:
            raise ValueError(f"Prix invalide pour « {l.label} ».")
    unknown = set(fields) - set(FIELDS)
    if unknown:
        raise ValueError(f"Champs inconnus : {', '.join(sorted(unknown))}")
    with session_scope() as session:
        if proforma_id:
            p = session.get(Proforma, proforma_id)
            if p is None:
                raise ValueError("Proforma introuvable.")
            p.lines.clear()
            session.flush()
        else:
            when = date or datetime.now()
            seq, number = _next_number(session, when.year)
            p = Proforma(year=when.year, seq=seq, number=number, date=when)
            session.add(p)
        if date and proforma_id:
            p.date = date
        for k, v in fields.items():
            setattr(p, k, v if v is not None else "")
        for i, l in enumerate(lines):
            p.lines.append(ProformaLine(position=i, label=l.label.strip(), packaging=(l.packaging or "").strip(),
                                        quantity=l.quantity, unit=(l.unit or "").strip(), unit_price=l.unit_price))
        session.flush()
        return p.id


def duplicate(proforma_id: int) -> int:
    d = get(proforma_id)
    fields = {k: d[k] for k in FIELDS}
    return save([LineInput(l["label"], l["quantity"], l["unit"], l["unit_price"], l["packaging"]) for l in d["lines"]], **fields)


def get(proforma_id: int) -> dict:
    with session_scope() as session:
        p = session.get(Proforma, proforma_id)
        if p is None:
            raise ValueError("Proforma introuvable.")
        d = {c: getattr(p, c) for c in ("id", "number", "date", "status", *FIELDS)}
        d["tax_rate"] = float(d["tax_rate"] or 0)
        d["lines"] = [dict(label=l.label, packaging=l.packaging, quantity=float(l.quantity), unit=l.unit, unit_price=float(l.unit_price)) for l in p.lines]
    d["totals"] = compute_totals([LineInput(**l) for l in d["lines"]], d["tax_label"], d["tax_rate"])
    return d


def list_all(status: Optional[str] = None) -> list[dict]:
    with session_scope() as session:
        stmt = select(Proforma).order_by(Proforma.date.desc(), Proforma.id.desc())
        if status:
            stmt = stmt.where(Proforma.status == status)
        ids = [p.id for p in session.scalars(stmt)]
    out = []
    for i in ids:
        d = get(i)
        out.append(dict(id=d["id"], number=d["number"], date=d["date"], client=d["client_name"], subject=d["subject"], status=d["status"], total=d["totals"].total))
    return out


def set_status(proforma_id: int, status: str) -> None:
    if status not in STATUSES:
        raise ValueError("Statut inconnu.")
    with session_scope() as session:
        p = session.get(Proforma, proforma_id)
        if p is None:
            raise ValueError("Proforma introuvable.")
        p.status = status


def delete(proforma_id: int) -> None:
    with session_scope() as session:
        p = session.get(Proforma, proforma_id)
        if p is not None:
            session.delete(p)


def suggest_products(proforma_id: int) -> list[Optional[int]]:
    """Produit probable de chaque ligne (même nom, sans tenir compte de la casse) ; None si aucun."""
    from app.models.product import Product

    d = get(proforma_id)
    with session_scope() as session:
        by_name = {p.name.strip().lower(): p.id for p in session.scalars(select(Product))}
    return [by_name.get(l["label"].strip().lower()) for l in d["lines"]]


def convert_to_sale(proforma_id: int, product_ids: list[Optional[int]], *, on_credit: bool = False, user_id: Optional[int] = None) -> int:
    """Transforme la proforma en vente : stock sorti, paiement en espèces ou dette du client (fiche client requise)."""
    from app.controllers.sale_controller import CartLine, PaymentLine, SaleController
    from app.models.product import Product

    d = get(proforma_id)
    if d["status"] == "Facturée":
        raise ValueError("Cette proforma est déjà transformée en vente.")
    if len(product_ids) != len(d["lines"]) or any(not pid for pid in product_ids):
        raise ValueError("Associez chaque ligne à un produit du stock.")
    if on_credit and not d["client_id"]:
        raise ValueError("Pour vendre à crédit, choisissez un client existant dans la proforma.")
    cart = []
    with session_scope() as session:
        for line, pid in zip(d["lines"], product_ids):
            product = session.get(Product, pid)
            if product is None:
                raise ValueError(f"Produit introuvable pour « {line['label']} ».")
            cart.append(CartLine(product_id=pid, name=product.name, unit_price=line["unit_price"], quantity=line["quantity"],
                                 purchase_price=float(product.purchase_price or 0)))
    total = round(sum(c.unit_price * c.quantity for c in cart), 2)
    payments = [] if on_credit else [PaymentLine("Espèces", total)]
    result = SaleController.create_sale(cart, payments, amount_received=0 if on_credit else total, client_id=d["client_id"],
                                        user_id=user_id, allow_credit=on_credit)
    with session_scope() as session:
        p = session.get(Proforma, proforma_id)
        p.status, p.sale_id = "Facturée", result.sale_id
    return result.sale_id


def client_defaults(client_id: int) -> dict:
    """Pré-remplissage depuis la fiche client existante (les champs fiscaux se saisissent sur la proforma)."""
    from app.models.client import Client

    with session_scope() as session:
        c = session.get(Client, client_id)
        if c is None:
            return {}
        return dict(client_id=c.id, client_name=c.name, client_phone=c.phone or "", client_email=c.email or "", client_address=c.address or "")


def defaults() -> dict:
    g = settings_service.get_setting
    return dict(responsible=g(SETTING_RESPONSIBLE, ""), responsible_phone=g(SETTING_RESPONSIBLE_PHONE, ""))


EXAMPLE_SUBJECT = "Exemple – Boucherie Wend Malgré"


def install_example() -> int:
    """Remplit les réglages proforma au modèle « Boucherie Wend Malgré » et crée une proforma d'exemple (une seule).

    L'image d'en-tête n'est pas touchée : quand elle est choisie (ou changée) dans Paramètres, elle remplace le haut de
    cette proforma comme de toutes les autres, puisqu'elle est lue à chaque impression."""
    set_enabled(True)
    for key, value in ((SETTING_TAGLINE, "Vente de la viande – Poisson – Poulet"), (SETTING_HEADER_EXTRA, "Secteur 42 Bendogo"),
                       (SETTING_CITY, "Ouagadougou"), (SETTING_RESPONSIBLE, "KABORE John Didier"),
                       (SETTING_RESPONSIBLE_PHONE, "70 43 46 43")):
        settings_service.set_setting(key, value)
    for row in list_all():
        if row.get("subject") == EXAMPLE_SUBJECT:
            return row["id"]
    return save(
        [LineInput("Viande de bœuf avec os", 50, "kg", 2500), LineInput("Poulet entier", 30, "kg", 2200),
         LineInput("Poisson (carpe)", 20, "kg", 2000)],
        client_name="Client exemple", client_phone="", subject=EXAMPLE_SUBJECT,
        responsible="KABORE John Didier", responsible_phone="70 43 46 43")
