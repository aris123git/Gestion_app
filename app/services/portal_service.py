"""Association du logiciel à un portail web (consultation lecture seule).

Identifiants machine (POS → site) :
- ``enterprise_id`` : identifiant entreprise / magasin
- ``api_key`` : clé secrète d'API (jamais affichée en clair après coup si masquée)

Le portail associé reçoit des snapshots d'indicateurs (CA, dettes, trésorerie…)
et permet de les consulter sans accéder à la base SQLite locale.
"""

from __future__ import annotations

import json
import logging
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urljoin

from app.services import settings_service

logger = logging.getLogger(__name__)

SETTING_ENABLED = "portal_enabled"
SETTING_URL = "portal_url"
SETTING_ENTERPRISE_ID = "portal_enterprise_id"
SETTING_API_KEY = "portal_api_key"
SETTING_OWNER_EMAIL = "portal_owner_email"
SETTING_ASSOCIATED = "portal_associated"
SETTING_LAST_SYNC = "portal_last_sync"
SETTING_LAST_ERROR = "portal_last_error"

DEFAULT_PORTAL_URL = "http://127.0.0.1:8787"


@dataclass
class PortalResult:
    ok: bool
    message: str
    data: Optional[dict] = None


def is_enabled() -> bool:
    return settings_service.get_setting(SETTING_ENABLED, "0") == "1"


def get_portal_url() -> str:
    return (settings_service.get_setting(SETTING_URL, DEFAULT_PORTAL_URL) or DEFAULT_PORTAL_URL).strip().rstrip("/")


def get_enterprise_id() -> str:
    return (settings_service.get_setting(SETTING_ENTERPRISE_ID, "") or "").strip()


def get_api_key() -> str:
    return (settings_service.get_setting(SETTING_API_KEY, "") or "").strip()


def get_owner_email() -> str:
    return (settings_service.get_setting(SETTING_OWNER_EMAIL, "") or "").strip()


def is_associated() -> bool:
    return settings_service.get_setting(SETTING_ASSOCIATED, "0") == "1"


def get_last_sync() -> str:
    return settings_service.get_setting(SETTING_LAST_SYNC, "") or ""


def get_last_error() -> str:
    return settings_service.get_setting(SETTING_LAST_ERROR, "") or ""


def ensure_credentials() -> tuple[str, str]:
    """Crée enterprise_id + api_key s'ils manquent ; retourne (id, clé)."""
    eid = get_enterprise_id()
    key = get_api_key()
    if not eid:
        eid = "ENT-" + secrets.token_hex(4).upper()
        settings_service.set_setting(SETTING_ENTERPRISE_ID, eid)
    if not key:
        key = secrets.token_urlsafe(32)
        settings_service.set_setting(SETTING_API_KEY, key)
    return eid, key


def regenerate_api_key() -> str:
    """Nouvelle clé API (invalide l'association jusqu'à ré-association)."""
    key = secrets.token_urlsafe(32)
    settings_service.set_setting(SETTING_API_KEY, key)
    settings_service.set_setting(SETTING_ASSOCIATED, "0")
    return key


def save_portal_settings(
    *,
    enabled: bool,
    url: str,
    owner_email: str = "",
    enterprise_id: Optional[str] = None,
) -> None:
    settings_service.set_setting(SETTING_ENABLED, "1" if enabled else "0")
    settings_service.set_setting(SETTING_URL, (url or DEFAULT_PORTAL_URL).strip().rstrip("/"))
    settings_service.set_setting(SETTING_OWNER_EMAIL, (owner_email or "").strip())
    if enterprise_id is not None:
        cleaned = (enterprise_id or "").strip()
        if cleaned:
            settings_service.set_setting(SETTING_ENTERPRISE_ID, cleaned)
    ensure_credentials()


def build_snapshot() -> dict[str, Any]:
    """Indicateurs entreprise à publier sur le portail (lecture seule)."""
    from app.services.dashboard_service import DashboardService

    shop = settings_service.get_shop_info()
    summary = DashboardService.financial_summary()
    return {
        "shop": {
            "name": shop.name or "",
            "address": shop.address or "",
            "phone": shop.phone or "",
            "email": shop.email or "",
            "currency": shop.currency or "FCFA",
            "shop_type": shop.shop_type or "",
        },
        "metrics": summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _request(
    method: str,
    path: str,
    payload: Optional[dict] = None,
    *,
    auth: bool = True,
    timeout: float = 12.0,
) -> PortalResult:
    base = get_portal_url()
    if not base:
        return PortalResult(False, "URL du portail non configurée.")
    url = urljoin(base + "/", path.lstrip("/"))
    body = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "NexaPOS-GestionCommerciale/1.0",
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if auth:
        eid, key = ensure_credentials()
        headers["X-Enterprise-Id"] = eid
        headers["X-Api-Key"] = key

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            data = json.loads(raw) if raw.strip() else {}
            if resp.status >= 400:
                return PortalResult(
                    False,
                    data.get("error") or f"Erreur HTTP {resp.status}",
                    data,
                )
            return PortalResult(True, data.get("message") or "OK", data)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")
            parsed = json.loads(detail) if detail else {}
            detail = parsed.get("error") or detail
        except Exception:
            parsed = {}
        msg = detail or f"HTTP {exc.code}"
        settings_service.set_setting(SETTING_LAST_ERROR, str(msg)[:500])
        return PortalResult(False, str(msg), parsed if isinstance(parsed, dict) else None)
    except urllib.error.URLError as exc:
        msg = (
            f"Portail injoignable ({exc.reason}). "
            "Vérifiez l'URL et que le site est démarré."
        )
        settings_service.set_setting(SETTING_LAST_ERROR, msg[:500])
        return PortalResult(False, msg)
    except Exception as exc:
        logger.exception("Appel portail impossible")
        settings_service.set_setting(SETTING_LAST_ERROR, str(exc)[:500])
        return PortalResult(False, f"Échec de communication : {exc}")


def associate() -> PortalResult:
    """Enregistre l'entreprise sur le portail (lien logiciel ↔ site)."""
    if not is_enabled():
        return PortalResult(
            False,
            "Activez d'abord « Associer au portail web » dans Paramètres.",
        )
    eid, key = ensure_credentials()
    shop = settings_service.get_shop_info()
    payload = {
        "enterprise_id": eid,
        "api_key": key,
        "shop_name": shop.name or "Commerce",
        "owner_email": get_owner_email() or (shop.email or ""),
        "currency": shop.currency or "FCFA",
        "shop_type": shop.shop_type or "",
    }
    result = _request("POST", "/api/v1/associate", payload, auth=False)
    if result.ok:
        settings_service.set_setting(SETTING_ASSOCIATED, "1")
        settings_service.set_setting(SETTING_LAST_ERROR, "")
        result.message = (
            result.message
            or f"Association réussie. Identifiant entreprise : {eid}"
        )
    return result


def sync_now() -> PortalResult:
    """Envoie un snapshot des indicateurs au portail associé."""
    if not is_enabled():
        return PortalResult(False, "Portail web désactivé.")
    if not is_associated():
        linked = associate()
        if not linked.ok:
            return linked
    snapshot = build_snapshot()
    eid = get_enterprise_id()
    payload = {"enterprise_id": eid, "snapshot": snapshot}
    result = _request("POST", "/api/v1/sync", payload, auth=True)
    if result.ok:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        settings_service.set_setting(SETTING_LAST_SYNC, stamp)
        settings_service.set_setting(SETTING_LAST_ERROR, "")
        result.message = result.message or f"Données publiées sur le portail ({stamp})."
    return result


def test_connection() -> PortalResult:
    """Ping du portail (sans auth) pour vérifier l'URL."""
    return _request("GET", "/api/v1/health", auth=False)


def status_summary() -> str:
    if not is_enabled():
        return "Portail web désactivé."
    parts = [f"URL : {get_portal_url()}", f"Entreprise : {get_enterprise_id() or '—'}"]
    parts.append("Associé" if is_associated() else "Non associé")
    if get_last_sync():
        parts.append(f"Dernière sync : {get_last_sync()}")
    if get_last_error():
        parts.append(f"Dernière erreur : {get_last_error()}")
    return " · ".join(parts)
