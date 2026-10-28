"""Contrôle d'intégrité des données : détecte les écarts sans rien modifier.

Vérifie la base SQLite, le stock, les couches de prix FIFO, les dettes clients,
les ventes, les numéros séquentiels et l'équilibre des écritures comptables.
Seule la réparation du solde client (cache recalculé) est proposée.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select, text

from app.database.connection import engine, session_scope
from app.models.client import Client
from app.models.debt import ACTIVE_DEBT_STATUSES, STATUS_CANCELLED, STATUS_PAID, Debt, DebtPayment
from app.models.price_layer import PriceLayer
from app.models.product import Product
from app.models.sale import Sale

logger = logging.getLogger(__name__)
TOL = 0.01
MAX_DETAILS = 25


@dataclass
class Issue:
    area: str
    message: str


def _f(v) -> float:
    return float(v or 0)


def run_checks() -> list[Issue]:
    """Retourne la liste des anomalies (vide = tout est cohérent)."""
    issues: list[Issue] = []

    with engine.connect() as conn:
        res = conn.execute(text("PRAGMA integrity_check")).fetchall()
        if not res or res[0][0] != "ok":
            issues.append(Issue("Base", "La base SQLite signale une corruption : " + "; ".join(str(r[0]) for r in res[:3])))
        for row in conn.execute(text("PRAGMA foreign_key_check")).fetchall()[:MAX_DETAILS]:
            issues.append(Issue("Base", f"Référence orpheline : table {row[0]}, ligne {row[1]} → {row[2]}"))

    with session_scope() as s:
        # Stock négatif
        for p in s.scalars(select(Product).where(Product.is_active.is_(True))):
            if not getattr(p, "sell_without_stock", False) and _f(p.quantity) < -TOL:
                issues.append(Issue("Stock", f"{p.name} : stock négatif ({_f(p.quantity):g})."))
        # Couches FIFO
        remaining = dict(s.execute(select(PriceLayer.product_id, func.coalesce(func.sum(PriceLayer.remaining), 0)).group_by(PriceLayer.product_id)).all())
        for p in s.scalars(select(Product).where(Product.id.in_(list(remaining) or [0]))):
            if _f(remaining[p.id]) > _f(p.quantity) + TOL:
                issues.append(Issue("Stock/prix", f"{p.name} : les lots en attente ({_f(remaining[p.id]):g}) dépassent le stock ({_f(p.quantity):g})."))
        # Dettes
        paid = dict(s.execute(select(DebtPayment.debt_id, func.coalesce(func.sum(DebtPayment.amount), 0)).group_by(DebtPayment.debt_id)).all())
        for d in s.scalars(select(Debt).where(Debt.status != STATUS_CANCELLED)):
            expected = _f(d.amount_initial) - _f(paid.get(d.id, 0))
            if _f(d.amount_remaining) < -TOL:
                issues.append(Issue("Dettes", f"Dette n°{d.id} : reste négatif ({_f(d.amount_remaining):g})."))
            elif abs(max(expected, 0) - _f(d.amount_remaining)) > TOL and d.status in ACTIVE_DEBT_STATUSES + (STATUS_PAID,):
                issues.append(Issue("Dettes", f"Dette n°{d.id} : reste {_f(d.amount_remaining):g} ≠ initial − règlements ({expected:g})."))
        totals = dict(s.execute(select(Debt.client_id, func.coalesce(func.sum(Debt.amount_remaining), 0)).where(Debt.status.in_(ACTIVE_DEBT_STATUSES)).group_by(Debt.client_id)).all())
        for c in s.scalars(select(Client)):
            if abs(_f(c.debt) - _f(totals.get(c.id, 0))) > TOL:
                issues.append(Issue("Clients", f"{c.name} : solde affiché {_f(c.debt):g} ≠ dettes actives {_f(totals.get(c.id, 0)):g}."))
        # Ventes
        for sale in s.scalars(select(Sale).where(Sale.status == "completed")):
            if not sale.items:
                issues.append(Issue("Ventes", f"Vente {sale.ticket_number} : aucune ligne."))
        # Numéros en double
        for col in ("invoice_number", "pickup_number", "delivery_number"):
            column = getattr(Sale, col)
            for num, n in s.execute(select(column, func.count()).where(column != "").group_by(column).having(func.count() > 1)):
                issues.append(Issue("Numéros", f"{col} {num} attribué {n} fois."))

    try:
        from app.services import accounting_service

        for e in accounting_service.generate_entries(date.today()):
            if not e.balanced:
                issues.append(Issue("Comptabilité", f"Écriture {e.journal} {e.piece} déséquilibrée ({e.label})."))
    except Exception:
        logger.exception("Contrôle comptable impossible.")
        issues.append(Issue("Comptabilité", "Impossible de générer les écritures pour les contrôler."))
    return issues


def repair_client_balances() -> int:
    """Recalcule le solde de chaque client depuis ses dettes actives. Retourne le nombre corrigé."""
    from app.services.debt_service import DebtService

    fixed = 0
    with session_scope() as s:
        for c in s.scalars(select(Client)):
            before = _f(c.debt)
            if abs(DebtService.sync_client_debt_cache(s, c.id) - before) > TOL:
                fixed += 1
    return fixed


def summary(issues: list[Issue] | None = None) -> str:
    issues = run_checks() if issues is None else issues
    if not issues:
        return "✓ Aucune anomalie : stock, dettes, ventes, numéros et écritures sont cohérents."
    lines = [f"{len(issues)} anomalie(s) détectée(s) :"]
    lines += [f"• [{i.area}] {i.message}" for i in issues[:MAX_DETAILS]]
    if len(issues) > MAX_DETAILS:
        lines.append(f"… et {len(issues) - MAX_DETAILS} autre(s).")
    return "\n".join(lines)
