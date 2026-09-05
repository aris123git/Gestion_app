"""Portail web NexaPOS — consultation lecture seule des données entreprise.

Démarrage ::

    python -m portal
    # écoute http://127.0.0.1:8787

Identifiants de consultation (MVP) : ``enterprise_id`` + ``api_key``
(les mêmes que ceux générés dans Paramètres → Portail web du logiciel).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("NEXAPOS_PORTAL_PORT", "8787"))
HOST = os.environ.get("NEXAPOS_PORTAL_HOST", "127.0.0.1")
DATA_DIR = Path(
    os.environ.get(
        "NEXAPOS_PORTAL_DATA",
        str(Path(__file__).resolve().parent / "data"),
    )
)


def _hash_key(api_key: str) -> str:
    return hashlib.sha256((api_key or "").encode("utf-8")).hexdigest()


def _enterprise_path(enterprise_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", (enterprise_id or "").strip()) or "unknown"
    return DATA_DIR / f"{safe}.json"


def _load(enterprise_id: str) -> Optional[dict]:
    path = _enterprise_path(enterprise_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save(enterprise_id: str, data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _enterprise_path(enterprise_id)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(raw)


def _html_response(handler: BaseHTTPRequestHandler, code: int, html: str) -> None:
    raw = html.encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _check_auth(handler: BaseHTTPRequestHandler, enterprise_id: str) -> tuple[bool, str]:
    eid = (handler.headers.get("X-Enterprise-Id") or enterprise_id or "").strip()
    key = (handler.headers.get("X-Api-Key") or "").strip()
    if not eid or not key:
        return False, "Identifiants manquants (X-Enterprise-Id / X-Api-Key)."
    record = _load(eid)
    if not record:
        return False, "Entreprise inconnue. Associez d'abord le logiciel."
    if record.get("api_key_hash") != _hash_key(key):
        return False, "Clé API invalide."
    return True, eid


LOGIN_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>NexaPOS — Portail entreprise</title>
  <style>
    body { margin:0; font-family: "Segoe UI", system-ui, sans-serif; background:linear-gradient(160deg,#0f172a,#1e3a5f); color:#e2e8f0; min-height:100vh; display:flex; align-items:center; justify-content:center; padding:24px; }
    .card { width:100%; max-width:420px; background:#1e293b; border-radius:16px; padding:28px; box-shadow:0 20px 50px rgba(0,0,0,.35); }
    h1 { margin:0 0 8px; font-size:1.4rem; }
    p { color:#94a3b8; font-size:.92rem; line-height:1.45; }
    label { display:block; margin:14px 0 6px; font-size:.85rem; color:#94a3b8; }
    input { width:100%; padding:12px 14px; border-radius:10px; border:1px solid #334155; background:#0f172a; color:#e2e8f0; }
    button { margin-top:18px; width:100%; padding:12px; border:0; border-radius:10px; background:#38bdf8; color:#0f172a; font-weight:700; cursor:pointer; }
    .err { color:#fca5a5; margin-top:12px; font-size:.9rem; }
  </style>
</head>
<body>
  <form class="card" method="GET" action="/dashboard">
    <h1>Portail NexaPOS</h1>
    <p>Consultez les indicateurs de votre entreprise (lecture seule). Utilisez l’identifiant et la clé API générés dans le logiciel (Paramètres → Portail web).</p>
    <label>Identifiant entreprise</label>
    <input name="enterprise_id" required placeholder="ENT-XXXXXXXX" value="__EID__"/>
    <label>Clé API</label>
    <input name="api_key" type="password" required placeholder="Clé secrète"/>
    __ERROR__
    <button type="submit">Se connecter</button>
  </form>
</body>
</html>
"""


def _login_html(eid: str = "", error: str = "") -> str:
    error_html = f'<div class="err">{error}</div>' if error else ""
    return LOGIN_PAGE.replace("__EID__", eid or "").replace("__ERROR__", error_html)


def _fmt_money(value: Any, currency: str) -> str:
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        num = 0.0
    return f"{num:,.0f} {currency}".replace(",", " ")


def _dashboard_html(record: dict) -> str:
    shop = (record.get("snapshot") or {}).get("shop") or {}
    metrics = (record.get("snapshot") or {}).get("metrics") or {}
    currency = shop.get("currency") or record.get("currency") or "FCFA"
    name = shop.get("name") or record.get("shop_name") or "Entreprise"
    synced = record.get("synced_at") or "—"
    cards = [
        ("CA aujourd'hui", metrics.get("revenue_today")),
        ("CA semaine", metrics.get("revenue_week")),
        ("CA mois", metrics.get("revenue_month")),
        ("Bénéfice net jour", metrics.get("profit_net_today")),
        ("Dépenses jour", metrics.get("expenses_today")),
        ("Trésorerie", metrics.get("treasury")),
        ("Dettes clients", metrics.get("client_debts")),
        ("Dettes fournisseurs", metrics.get("supplier_debts")),
    ]
    cards_html = "".join(
        f'<div class="metric"><div class="label">{label}</div>'
        f'<div class="value">{_fmt_money(val, currency)}</div></div>'
        for label, val in cards
    )
    return (
        "<!DOCTYPE html><html lang=\"fr\"><head><meta charset=\"utf-8\"/>"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>"
        f"<title>{name} — Portail NexaPOS</title>"
        "<style>"
        "body{margin:0;font-family:Segoe UI,system-ui,sans-serif;background:#0b1220;color:#e2e8f0;}"
        "header{padding:28px 24px 12px;}h1{margin:0 0 6px;font-size:1.6rem;}"
        ".meta{color:#94a3b8;font-size:.92rem;}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px;padding:16px 24px 40px;}"
        ".metric{background:#1e293b;border-radius:14px;padding:16px;}"
        ".label{color:#94a3b8;font-size:.8rem;margin-bottom:8px;}"
        ".value{font-size:1.25rem;font-weight:700;}a{color:#38bdf8;}"
        "</style></head><body>"
        f"<header><h1>{name}</h1>"
        f"<div class=\"meta\">Lecture seule · Dernière synchronisation : {synced} · "
        "<a href=\"/\">Déconnexion</a></div></header>"
        f"<div class=\"grid\">{cards_html}</div></body></html>"
    )

class PortalHandler(BaseHTTPRequestHandler):
    server_version = "NexaPOSPortal/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path == "/api/v1/health":
            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "service": "nexapos-portal",
                    "message": "Portail opérationnel",
                    "time": datetime.now(timezone.utc).isoformat(),
                },
            )
            return

        if path in ("/", "/login"):
            err = qs.get("error", [""])[0]
            _html_response(
                self,
                200,
                _login_html(qs.get("enterprise_id", [""])[0], err),
            )
            return

        if path == "/dashboard":
            eid = (qs.get("enterprise_id") or [""])[0].strip()
            key = (qs.get("api_key") or [""])[0].strip()
            record = _load(eid) if eid else None
            if not record or record.get("api_key_hash") != _hash_key(key):
                self.send_response(302)
                self.send_header(
                    "Location",
                    "/login?error=Identifiants%20invalides",
                )
                self.end_headers()
                return
            if not record.get("snapshot"):
                _html_response(
                    self,
                    200,
                    _login_html(
                        eid,
                        "Entreprise associée, mais aucune donnée synchronisée pour l’instant. "
                        "Cliquez « Synchroniser » dans le logiciel.",
                    ),
                )
                return
            _html_response(self, 200, _dashboard_html(record))
            return

        _json_response(self, 404, {"error": "Route inconnue"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        payload = _read_json(self)

        if path == "/api/v1/associate":
            eid = (payload.get("enterprise_id") or "").strip()
            api_key = (payload.get("api_key") or "").strip()
            if not eid or not api_key:
                _json_response(self, 400, {"error": "enterprise_id et api_key requis"})
                return
            existing = _load(eid) or {}
            record = {
                **existing,
                "enterprise_id": eid,
                "api_key_hash": _hash_key(api_key),
                "shop_name": payload.get("shop_name") or existing.get("shop_name") or "",
                "owner_email": payload.get("owner_email") or existing.get("owner_email") or "",
                "currency": payload.get("currency") or existing.get("currency") or "FCFA",
                "shop_type": payload.get("shop_type") or existing.get("shop_type") or "",
                "associated_at": datetime.now(timezone.utc).isoformat(),
            }
            _save(eid, record)
            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "message": f"Entreprise « {eid} » associée au portail.",
                    "enterprise_id": eid,
                },
            )
            return

        if path == "/api/v1/sync":
            eid = (payload.get("enterprise_id") or "").strip()
            ok, detail = _check_auth(self, eid)
            if not ok:
                _json_response(self, 401, {"error": detail})
                return
            eid = detail
            snapshot = payload.get("snapshot") or {}
            record = _load(eid) or {"enterprise_id": eid}
            record["snapshot"] = snapshot
            record["synced_at"] = datetime.now(timezone.utc).isoformat()
            shop = snapshot.get("shop") or {}
            if shop.get("name"):
                record["shop_name"] = shop["name"]
            if shop.get("currency"):
                record["currency"] = shop["currency"]
            _save(eid, record)
            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "message": "Snapshot publié.",
                    "synced_at": record["synced_at"],
                },
            )
            return

        _json_response(self, 404, {"error": "Route inconnue"})


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), PortalHandler)
    print(f"Portail NexaPOS : http://{HOST}:{PORT}/", flush=True)
    print(f"Données : {DATA_DIR}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du portail.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
