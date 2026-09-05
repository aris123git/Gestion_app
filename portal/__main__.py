"""Portail web NexaPOS — multi-magasins, lecture seule (comme la caisse).

Démarrage ::

    python -m portal
    # http://127.0.0.1:8787

- **Mode bureau** : totaux consolidés (CA, bénéfice, ventes, dettes…) puis
  clic sur un magasin pour le détail.
- **Mode magasin** : identifiant entreprise + clé API → même navigation
  (tableau de bord, ventes, dettes, stock) en lecture seule.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, quote, urlparse

PORT = int(os.environ.get("NEXAPOS_PORTAL_PORT", "8787"))
HOST = os.environ.get("NEXAPOS_PORTAL_HOST", "127.0.0.1")
DATA_DIR = Path(
    os.environ.get(
        "NEXAPOS_PORTAL_DATA",
        str(Path(__file__).resolve().parent / "data"),
    )
)
BUREAU_FILE = DATA_DIR / "_bureau.json"
SESSIONS: dict[str, dict[str, Any]] = {}


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
    _enterprise_path(enterprise_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _list_enterprises() -> list[dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(DATA_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("enterprise_id"):
            rows.append(data)
    rows.sort(
        key=lambda r: (r.get("shop_name") or r.get("enterprise_id") or "").lower()
    )
    return rows


def _ensure_bureau() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if BUREAU_FILE.exists():
        try:
            return json.loads(BUREAU_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    password = os.environ.get("NEXAPOS_PORTAL_BUREAU_PASSWORD") or secrets.token_urlsafe(10)
    data = {
        "password_hash": _hash_key(password),
        "password_plain_once": password,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    BUREAU_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(
        f"Clé bureau portail (à conserver) : {password}",
        flush=True,
    )
    return data


def _bureau_ok(password: str) -> bool:
    data = _ensure_bureau()
    return _hash_key(password) == data.get("password_hash")


def _new_session(payload: dict) -> str:
    token = secrets.token_urlsafe(24)
    SESSIONS[token] = payload
    return token


def _session_from(handler: BaseHTTPRequestHandler) -> Optional[dict]:
    raw = handler.headers.get("Cookie") or ""
    jar = SimpleCookie()
    try:
        jar.load(raw)
    except Exception:
        return None
    morsel = jar.get("nexapos_portal")
    if not morsel:
        return None
    return SESSIONS.get(morsel.value)


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(raw)


def _html_response(
    handler: BaseHTTPRequestHandler,
    code: int,
    body: str,
    *,
    set_cookie: Optional[str] = None,
) -> None:
    raw = body.encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    if set_cookie:
        handler.send_header("Set-Cookie", set_cookie)
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


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _money(value: Any, currency: str = "FCFA") -> str:
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        num = 0.0
    return f"{num:,.0f} {currency}".replace(",", " ")


def _sum_metric(shops: list[dict], key: str) -> float:
    total = 0.0
    for shop in shops:
        metrics = (shop.get("snapshot") or {}).get("metrics") or {}
        try:
            total += float(metrics.get(key) or 0)
        except (TypeError, ValueError):
            pass
    return total


CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; font-family:"Segoe UI",system-ui,sans-serif; background:#0b1220; color:#e2e8f0; }
a { color:#38bdf8; text-decoration:none; }
header.app { display:flex; gap:16px; align-items:center; justify-content:space-between;
  padding:16px 22px; background:#111827; border-bottom:1px solid #1f2937; flex-wrap:wrap; }
header.app h1 { margin:0; font-size:1.15rem; }
.badge { font-size:.75rem; color:#94a3b8; }
nav.tabs { display:flex; gap:8px; flex-wrap:wrap; padding:12px 22px; background:#0f172a; border-bottom:1px solid #1f2937; }
nav.tabs a { padding:8px 12px; border-radius:999px; background:#1e293b; color:#e2e8f0; font-size:.9rem; }
nav.tabs a.active { background:#38bdf8; color:#0f172a; font-weight:700; }
.wrap { padding:18px 22px 40px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:12px; }
.card { background:#1e293b; border-radius:14px; padding:14px 16px; }
.card .label { color:#94a3b8; font-size:.78rem; margin-bottom:6px; }
.card .value { font-size:1.2rem; font-weight:700; }
.shop-list { display:grid; gap:10px; margin-top:16px; }
.shop-item { display:flex; justify-content:space-between; gap:12px; align-items:center;
  background:#1e293b; border-radius:12px; padding:14px 16px; }
.shop-item:hover { outline:1px solid #38bdf8; }
table { width:100%; border-collapse:collapse; background:#1e293b; border-radius:12px; overflow:hidden; }
th, td { padding:10px 12px; border-bottom:1px solid #334155; text-align:left; font-size:.9rem; }
th { color:#94a3b8; font-weight:600; background:#0f172a; }
.muted { color:#94a3b8; }
.ro { display:inline-block; margin-left:8px; padding:2px 8px; border-radius:999px;
  background:#334155; color:#cbd5e1; font-size:.7rem; }
.login-wrap { min-height:100vh; display:flex; align-items:center; justify-content:center; padding:24px;
  background:linear-gradient(160deg,#0f172a,#1e3a5f); }
.login-card { width:100%; max-width:460px; background:#1e293b; border-radius:16px; padding:28px; }
.login-card h1 { margin:0 0 8px; font-size:1.35rem; }
.login-card p { color:#94a3b8; line-height:1.45; }
label { display:block; margin:14px 0 6px; font-size:.85rem; color:#94a3b8; }
input { width:100%; padding:12px 14px; border-radius:10px; border:1px solid #334155;
  background:#0f172a; color:#e2e8f0; }
button, .btn { margin-top:16px; width:100%; padding:12px; border:0; border-radius:10px;
  background:#38bdf8; color:#0f172a; font-weight:700; cursor:pointer; display:inline-block; text-align:center; }
.err { color:#fca5a5; margin-top:12px; }
.hint { font-size:.85rem; color:#94a3b8; margin-top:10px; }
"""


def _shell(title: str, nav: str, content: str, subtitle: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(title)}</title><style>{CSS}</style></head>
<body>
<header class="app">
  <div>
    <h1>{_esc(title)} <span class="ro">LECTURE SEULE</span></h1>
    <div class="badge">{_esc(subtitle)}</div>
  </div>
  <div><a href="/logout">Déconnexion</a></div>
</header>
{nav}
<div class="wrap">{content}</div>
</body></html>"""


def _login_page(error: str = "", eid: str = "") -> str:
    err = f'<div class="err">{_esc(error)}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>NexaPOS — Portail</title><style>{CSS}</style></head>
<body><div class="login-wrap"><div class="login-card">
<h1>Portail NexaPOS</h1>
<p>Multi-magasins : ouvrez le <b>mode bureau</b> pour les totaux, puis cliquez un magasin.
Ou connectez un magasin seul (identifiant + clé API du logiciel).</p>
{err}
<form method="POST" action="/login/bureau">
  <h3 style="margin:18px 0 0;font-size:1rem;">Mode bureau (tous les coins)</h3>
  <label>Mot de passe bureau</label>
  <input name="password" type="password" required placeholder="Clé bureau du portail"/>
  <button type="submit">Voir les totaux consolidés</button>
</form>
<form method="POST" action="/login/shop" style="margin-top:28px;border-top:1px solid #334155;padding-top:8px;">
  <h3 style="margin:18px 0 0;font-size:1rem;">Un magasin</h3>
  <label>Identifiant entreprise</label>
  <input name="enterprise_id" required placeholder="ENT-XXXXXXXX" value="{_esc(eid)}"/>
  <label>Clé API</label>
  <input name="api_key" type="password" required/>
  <button type="submit">Ouvrir le magasin</button>
</form>
<p class="hint">Dans le logiciel : Paramètres → Portail web → Associer / Synchroniser.
Le mot de passe bureau s’affiche au premier démarrage de <code>python -m portal</code>.</p>
</div></div></body></html>"""


def _kpi_grid(metrics: dict, currency: str) -> str:
    cards = [
        ("CA aujourd'hui", metrics.get("revenue_today")),
        ("CA semaine", metrics.get("revenue_week")),
        ("CA mois", metrics.get("revenue_month")),
        ("Bénéfice net jour", metrics.get("profit_net_today")),
        ("Ventes / tickets jour", metrics.get("sales_today") or metrics.get("tickets_today")),
        ("Dépenses jour", metrics.get("expenses_today")),
        ("Trésorerie", metrics.get("treasury")),
        ("Dettes clients", metrics.get("client_debts")),
        ("Nb dettes", metrics.get("client_debts_count")),
        ("Dettes fournisseurs", metrics.get("supplier_debts")),
        ("Stock faible", metrics.get("low_stock")),
        ("Ruptures", metrics.get("out_of_stock")),
    ]
    parts = []
    for label, val in cards:
        if label in ("Ventes / tickets jour", "Nb dettes", "Stock faible", "Ruptures"):
            display = str(int(float(val or 0)))
        else:
            display = _money(val, currency)
        parts.append(
            f'<div class="card"><div class="label">{_esc(label)}</div>'
            f'<div class="value">{_esc(display)}</div></div>'
        )
    return '<div class="grid">' + "".join(parts) + "</div>"


def _bureau_page() -> str:
    shops = _list_enterprises()
    currency = "FCFA"
    if shops:
        currency = (
            ((shops[0].get("snapshot") or {}).get("shop") or {}).get("currency")
            or shops[0].get("currency")
            or "FCFA"
        )
    totals = {
        "revenue_today": _sum_metric(shops, "revenue_today"),
        "revenue_week": _sum_metric(shops, "revenue_week"),
        "revenue_month": _sum_metric(shops, "revenue_month"),
        "profit_net_today": _sum_metric(shops, "profit_net_today"),
        "sales_today": _sum_metric(shops, "sales_today"),
        "expenses_today": _sum_metric(shops, "expenses_today"),
        "treasury": _sum_metric(shops, "treasury"),
        "client_debts": _sum_metric(shops, "client_debts"),
        "client_debts_count": _sum_metric(shops, "client_debts_count"),
        "supplier_debts": _sum_metric(shops, "supplier_debts"),
        "low_stock": _sum_metric(shops, "low_stock"),
        "out_of_stock": _sum_metric(shops, "out_of_stock"),
    }
    items = []
    for shop in shops:
        eid = shop.get("enterprise_id") or ""
        snap = shop.get("snapshot") or {}
        meta = snap.get("shop") or {}
        name = meta.get("name") or shop.get("shop_name") or eid
        metrics = snap.get("metrics") or {}
        synced = shop.get("synced_at") or "jamais"
        items.append(
            f'<a class="shop-item" href="/shop/{quote(eid)}?view=dashboard">'
            f"<div><strong>{_esc(name)}</strong><div class=\"muted\">{_esc(eid)} · "
            f"sync {_esc(synced)}</div></div>"
            f"<div style=\"text-align:right\"><div>CA jour : "
            f"<b>{_esc(_money(metrics.get('revenue_today'), currency))}</b></div>"
            f"<div class=\"muted\">Dettes : "
            f"{_esc(_money(metrics.get('client_debts'), currency))}</div></div></a>"
        )
    content = (
        f"<p class=\"muted\">{len(shops)} magasin(s) synchronisé(s). "
        "Cliquez un magasin pour le détail (même logique que la caisse, lecture seule).</p>"
        + _kpi_grid(totals, currency)
        + '<h2 style="margin:22px 0 8px;font-size:1.05rem;">Magasins</h2>'
        + (
            '<div class="shop-list">' + "".join(items) + "</div>"
            if items
            else '<p class="muted">Aucun magasin associé pour l’instant.</p>'
        )
    )
    return _shell(
        "Bureau — totaux consolidés",
        "",
        content,
        "Tous les coins / points de vente",
    )


def _shop_nav(eid: str, view: str) -> str:
    links = [
        ("dashboard", "Tableau de bord"),
        ("ventes", "Ventes"),
        ("dettes", "Dettes"),
        ("stock", "Stock"),
    ]
    parts = []
    for key, label in links:
        cls = "active" if view == key else ""
        parts.append(
            f'<a class="{cls}" href="/shop/{quote(eid)}?view={key}">{label}</a>'
        )
    parts.append('<a href="/bureau">← Tous les magasins</a>')
    return "<nav class=\"tabs\">" + "".join(parts) + "</nav>"


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in row) + "</tr>")
    if not body:
        body.append(
            f'<tr><td colspan="{len(headers)}" class="muted">Aucune donnée synchronisée.</td></tr>'
        )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _shop_page(record: dict, view: str) -> str:
    eid = record.get("enterprise_id") or ""
    snap = record.get("snapshot") or {}
    shop = snap.get("shop") or {}
    metrics = snap.get("metrics") or {}
    currency = shop.get("currency") or record.get("currency") or "FCFA"
    name = shop.get("name") or record.get("shop_name") or eid
    synced = record.get("synced_at") or "—"

    if view == "ventes":
        rows = [
            [
                s.get("ticket"),
                (s.get("date") or "")[:19].replace("T", " "),
                s.get("cashier"),
                s.get("payment"),
                _money(s.get("total"), currency),
                s.get("status"),
            ]
            for s in (snap.get("sales") or [])
        ]
        content = _table(
            ["Ticket", "Date", "Caissier", "Paiement", "Total", "Statut"], rows
        )
    elif view == "dettes":
        rows = [
            [
                (d.get("date") or "")[:10],
                d.get("client"),
                d.get("phone"),
                _money(d.get("initial"), currency),
                _money(d.get("remaining"), currency),
                (d.get("due_date") or "")[:10],
                d.get("status"),
                d.get("ticket"),
            ]
            for d in (snap.get("debts") or [])
        ]
        content = _table(
            [
                "Date",
                "Client",
                "Téléphone",
                "Initial",
                "Reste",
                "Échéance",
                "Statut",
                "Vente",
            ],
            rows,
        )
    elif view == "stock":
        rows = [
            [
                p.get("name"),
                p.get("category"),
                p.get("barcode"),
                _money(p.get("sale_price"), currency),
                p.get("quantity"),
                p.get("unit"),
            ]
            for p in (snap.get("products") or [])
        ]
        content = (
            f"<p class=\"muted\">Produits actifs synchronisés · "
            f"stock faible : {int(float(metrics.get('low_stock') or 0))} · "
            f"ruptures : {int(float(metrics.get('out_of_stock') or 0))}</p>"
            + _table(
                ["Nom", "Catégorie", "Code-barres", "Prix", "Stock", "Unité"],
                rows,
            )
        )
    else:
        content = (
            f"<p class=\"muted\">Dernière sync : {_esc(synced)}</p>"
            + _kpi_grid(metrics, currency)
        )

    return _shell(
        name,
        _shop_nav(eid, view),
        content,
        f"{eid} · affichage type caisse, options en lecture seule",
    )


class PortalHandler(BaseHTTPRequestHandler):
    server_version = "NexaPOSPortal/2.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)
        session = _session_from(self)

        if path == "/api/v1/health":
            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "service": "nexapos-portal",
                    "message": "Portail opérationnel",
                    "shops": len(_list_enterprises()),
                    "time": datetime.now(timezone.utc).isoformat(),
                },
            )
            return

        if path == "/logout":
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", "nexapos_portal=; Path=/; Max-Age=0")
            self.end_headers()
            return

        if path in ("/", "/login"):
            if session and session.get("role") == "bureau":
                self.send_response(302)
                self.send_header("Location", "/bureau")
                self.end_headers()
                return
            if session and session.get("role") == "shop":
                eid = session.get("enterprise_id") or ""
                self.send_response(302)
                self.send_header("Location", f"/shop/{quote(eid)}?view=dashboard")
                self.end_headers()
                return
            _html_response(
                self,
                200,
                _login_page(qs.get("error", [""])[0], qs.get("enterprise_id", [""])[0]),
            )
            return

        if path == "/bureau":
            if not session or session.get("role") != "bureau":
                self.send_response(302)
                self.send_header("Location", "/login?error=Connexion%20bureau%20requise")
                self.end_headers()
                return
            _html_response(self, 200, _bureau_page())
            return

        if path.startswith("/shop/"):
            eid = path.split("/shop/", 1)[1].strip("/")
            view = (qs.get("view") or ["dashboard"])[0]
            if view not in ("dashboard", "ventes", "dettes", "stock"):
                view = "dashboard"
            allowed = False
            if session and session.get("role") == "bureau":
                allowed = True
            elif (
                session
                and session.get("role") == "shop"
                and session.get("enterprise_id") == eid
            ):
                allowed = True
            if not allowed:
                self.send_response(302)
                self.send_header("Location", "/login?error=Connexion%20requise")
                self.end_headers()
                return
            record = _load(eid)
            if not record:
                _html_response(self, 404, _login_page("Magasin introuvable."))
                return
            if not record.get("snapshot"):
                _html_response(
                    self,
                    200,
                    _shell(
                        "Magasin",
                        _shop_nav(eid, view),
                        "<p class=\"muted\">Aucune donnée synchronisée. "
                        "Dans le logiciel : Portail web → Synchroniser.</p>",
                        eid,
                    ),
                )
                return
            _html_response(self, 200, _shop_page(record, view))
            return

        _json_response(self, 404, {"error": "Route inconnue"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/login/bureau":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
            form = parse_qs(raw)
            password = (form.get("password") or [""])[0]
            if not _bureau_ok(password):
                _html_response(self, 401, _login_page("Mot de passe bureau invalide."))
                return
            # Forget one-time plain password after first successful use display period
            bureau = _ensure_bureau()
            if "password_plain_once" in bureau:
                bureau.pop("password_plain_once", None)
                BUREAU_FILE.write_text(json.dumps(bureau, indent=2), encoding="utf-8")
            token = _new_session({"role": "bureau"})
            self.send_response(302)
            self.send_header("Location", "/bureau")
            self.send_header(
                "Set-Cookie",
                f"nexapos_portal={token}; Path=/; HttpOnly; SameSite=Lax",
            )
            self.end_headers()
            return

        if path == "/login/shop":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
            form = parse_qs(raw)
            eid = (form.get("enterprise_id") or [""])[0].strip()
            key = (form.get("api_key") or [""])[0].strip()
            record = _load(eid) if eid else None
            if not record or record.get("api_key_hash") != _hash_key(key):
                _html_response(
                    self, 401, _login_page("Identifiants magasin invalides.", eid)
                )
                return
            token = _new_session({"role": "shop", "enterprise_id": eid})
            self.send_response(302)
            self.send_header("Location", f"/shop/{quote(eid)}?view=dashboard")
            self.send_header(
                "Set-Cookie",
                f"nexapos_portal={token}; Path=/; HttpOnly; SameSite=Lax",
            )
            self.end_headers()
            return

        payload = _read_json(self)

        if path == "/api/v1/associate":
            eid = (payload.get("enterprise_id") or "").strip()
            api_key = (payload.get("api_key") or "").strip()
            if not eid or not api_key:
                _json_response(self, 400, {"error": "enterprise_id et api_key requis"})
                return
            _ensure_bureau()
            existing = _load(eid) or {}
            record = {
                **existing,
                "enterprise_id": eid,
                "api_key_hash": _hash_key(api_key),
                "shop_name": payload.get("shop_name") or existing.get("shop_name") or "",
                "owner_email": payload.get("owner_email")
                or existing.get("owner_email")
                or "",
                "currency": payload.get("currency") or existing.get("currency") or "FCFA",
                "shop_type": payload.get("shop_type") or existing.get("shop_type") or "",
                "associated_at": datetime.now(timezone.utc).isoformat(),
            }
            _save(eid, record)
            bureau = _ensure_bureau()
            msg = f"Entreprise « {eid} » associée au portail."
            plain = bureau.get("password_plain_once")
            if plain:
                msg += f" Mot de passe bureau (une fois) : {plain}"
            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "message": msg,
                    "enterprise_id": eid,
                    "bureau_password_once": plain,
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
                    "message": "Snapshot publié (indicateurs + ventes + dettes + stock).",
                    "synced_at": record["synced_at"],
                },
            )
            return

        _json_response(self, 404, {"error": "Route inconnue"})


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_bureau()
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
