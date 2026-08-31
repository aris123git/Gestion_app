"""Sync multi-magasins Lot 1 : export / import JSON via dossier partagé."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select

from app import config
from app.controllers.report_controller import ReportController
from app.database.connection import session_scope
from app.models.enterprise import EnterpriseSnapshot
from app.services import settings_service
from app.services.dashboard_service import DashboardService

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
SETTING_SHOP_ID = "enterprise_shop_id"
SETTING_SHOP_CODE = "enterprise_shop_code"
SETTING_MODE = "enterprise_mode"  # magasin | bureau | both
SETTING_SHARE_PATH = "enterprise_share_path"


@dataclass
class SyncResult:
    ok: bool
    message: str
    path: str = ""
    count: int = 0


def ensure_shop_identity() -> tuple[str, str]:
    """Garantit un shop_id UUID et un code court (ex. MAG-01)."""
    shop_id = (settings_service.get_setting(SETTING_SHOP_ID, "") or "").strip()
    if not shop_id:
        shop_id = str(uuid.uuid4())
        settings_service.set_setting(SETTING_SHOP_ID, shop_id)
    code = (settings_service.get_setting(SETTING_SHOP_CODE, "") or "").strip()
    if not code:
        code = f"MAG-{shop_id[:4].upper()}"
        settings_service.set_setting(SETTING_SHOP_CODE, code)
    return shop_id, code


def share_directory() -> Path:
    """Dossier partagé configuré, sinon outbox local ``DATA_DIR/reseau``."""
    raw = (settings_service.get_setting(SETTING_SHARE_PATH, "") or "").strip()
    if raw:
        path = Path(raw).expanduser()
    else:
        path = config.DATA_DIR / "reseau"
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_day_snapshot(day: Optional[date] = None) -> Dict[str, Any]:
    """Construit le JSON du jour pour ce magasin."""
    day = day or date.today()
    shop_id, shop_code = ensure_shop_identity()
    shop = settings_service.get_shop_info()
    report = ReportController.build(day, day)
    fin = DashboardService.financial_summary()
    return {
        "schema": SCHEMA_VERSION,
        "shop_id": shop_id,
        "shop_code": shop_code,
        "shop_name": shop.name or shop_code,
        "currency": shop.currency or "FCFA",
        "period": "day",
        "date": day.isoformat(),
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "metrics": {
            "cash_revenue": float(report.get("cash_revenue") or 0),
            "profit_gross": float(report.get("profit") or 0),
            "profit_net": float(report.get("net_profit") or 0),
            "expenses": float(report.get("expenses") or 0),
            "sales_count": int(report.get("sales_count") or 0),
            "client_debts": float(fin.get("client_debts") or 0),
            "client_debts_count": int(fin.get("client_debts_count") or 0),
            "debt_repayments": float(report.get("debt_repayments") or 0),
            "treasury": float(report.get("treasury") or fin.get("treasury") or 0),
        },
    }


def export_day_to_share(day: Optional[date] = None) -> SyncResult:
    """Écrit `{shop_id}_{date}.json` dans le dossier partagé."""
    day = day or date.today()
    try:
        payload = build_day_snapshot(day)
        folder = share_directory()
        filename = f"{payload['shop_id']}_{day.isoformat()}.json"
        path = folder / filename
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return SyncResult(
            ok=True,
            message=f"Export OK pour {day.isoformat()}.",
            path=str(path),
            count=1,
        )
    except Exception as exc:
        logger.exception("Export multi-magasins échoué")
        return SyncResult(ok=False, message=str(exc))


def _upsert_snapshot(payload: Dict[str, Any], source_path: str) -> bool:
    try:
        report_date = date.fromisoformat(str(payload.get("date") or ""))
    except ValueError:
        return False
    shop_id = str(payload.get("shop_id") or "").strip()
    if not shop_id:
        return False
    metrics = payload.get("metrics") or {}
    with session_scope() as session:
        existing = session.scalar(
            select(EnterpriseSnapshot).where(
                EnterpriseSnapshot.shop_id == shop_id,
                EnterpriseSnapshot.report_date == report_date,
            )
        )
        if existing is None:
            existing = EnterpriseSnapshot(shop_id=shop_id, report_date=report_date)
            session.add(existing)
        existing.shop_code = str(payload.get("shop_code") or "")
        existing.shop_name = str(payload.get("shop_name") or "")
        existing.currency = str(payload.get("currency") or "FCFA")
        existing.cash_revenue = float(metrics.get("cash_revenue") or 0)
        existing.profit_gross = float(metrics.get("profit_gross") or 0)
        existing.profit_net = float(metrics.get("profit_net") or 0)
        existing.expenses = float(metrics.get("expenses") or 0)
        existing.sales_count = int(metrics.get("sales_count") or 0)
        existing.client_debts = float(metrics.get("client_debts") or 0)
        existing.client_debts_count = int(metrics.get("client_debts_count") or 0)
        existing.debt_repayments = float(metrics.get("debt_repayments") or 0)
        existing.treasury = float(metrics.get("treasury") or 0)
        existing.source_path = source_path
        existing.imported_at = datetime.now()
    return True


def scan_and_import(folder: Optional[Path] = None) -> SyncResult:
    """Importe tous les ``*.json`` du dossier partagé."""
    folder = folder or share_directory()
    if not folder.exists():
        return SyncResult(ok=False, message=f"Dossier introuvable : {folder}")
    imported = 0
    errors = 0
    for path in sorted(folder.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                errors += 1
                continue
            if _upsert_snapshot(payload, str(path)):
                imported += 1
            else:
                errors += 1
        except Exception:
            logger.exception("Import échoué pour %s", path)
            errors += 1
    msg = f"{imported} fichier(s) importé(s)"
    if errors:
        msg += f", {errors} ignoré(s)"
    return SyncResult(ok=True, message=msg, path=str(folder), count=imported)


def ranking_for_day(day: Optional[date] = None) -> List[EnterpriseSnapshot]:
    """Magasins classés par CA décroissant pour une journée."""
    day = day or date.today()
    with session_scope() as session:
        rows = session.scalars(
            select(EnterpriseSnapshot)
            .where(EnterpriseSnapshot.report_date == day)
            .order_by(EnterpriseSnapshot.cash_revenue.desc())
        ).all()
        # Détacher pour usage hors session
        session.expunge_all()
        return list(rows)


def consolidated_for_day(day: Optional[date] = None) -> Dict[str, Any]:
    """Totaux tous magasins pour une journée."""
    day = day or date.today()
    with session_scope() as session:
        row = session.execute(
            select(
                func.coalesce(func.sum(EnterpriseSnapshot.cash_revenue), 0),
                func.coalesce(func.sum(EnterpriseSnapshot.profit_gross), 0),
                func.coalesce(func.sum(EnterpriseSnapshot.profit_net), 0),
                func.coalesce(func.sum(EnterpriseSnapshot.expenses), 0),
                func.coalesce(func.sum(EnterpriseSnapshot.sales_count), 0),
                func.coalesce(func.sum(EnterpriseSnapshot.client_debts), 0),
                func.count(EnterpriseSnapshot.id),
            ).where(EnterpriseSnapshot.report_date == day)
        ).one()
    return {
        "date": day,
        "cash_revenue": float(row[0] or 0),
        "profit_gross": float(row[1] or 0),
        "profit_net": float(row[2] or 0),
        "expenses": float(row[3] or 0),
        "sales_count": int(row[4] or 0),
        "client_debts": float(row[5] or 0),
        "shop_count": int(row[6] or 0),
    }


def shop_detail(shop_id: str, day: Optional[date] = None) -> Optional[EnterpriseSnapshot]:
    day = day or date.today()
    with session_scope() as session:
        row = session.scalar(
            select(EnterpriseSnapshot).where(
                EnterpriseSnapshot.shop_id == shop_id,
                EnterpriseSnapshot.report_date == day,
            )
        )
        if row is None:
            return None
        session.expunge(row)
        return row
