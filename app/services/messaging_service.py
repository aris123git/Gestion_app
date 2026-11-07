"""Messages aux clients : segments (période d'achat, inactifs, dettes), WhatsApp en file, e-mail séquentiel.

Garde-fous contre le spam : jamais les clients « ne plus contacter », plafond quotidien par canal, délai entre
deux e-mails, pas de répétition vers un même client avant N jours, mention de désinscription, journal des envois.
WhatsApp n'est jamais envoyé automatiquement : on ouvre la conversation pré-remplie et c'est la personne qui valide.
"""

from __future__ import annotations

import re
import smtplib
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Callable, List, Optional
from urllib.parse import quote

from sqlalchemy import func, select

from app.database.connection import session_scope
from app.models.client import Client
from app.models.message_log import MessageLog
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.services import settings_service

WHATSAPP = "whatsapp"
EMAIL = "email"
SENT, SKIPPED, FAILED = "envoye", "ignore", "echec"

SEG_ALL = "all"
SEG_BOUGHT = "bought_between"
SEG_INACTIVE = "inactive"
SEG_DEBT = "with_debt"
SEG_CATEGORY = "bought_category"
SEGMENT_LABELS = {
    SEG_ALL: "Tous les clients",
    SEG_BOUGHT: "Ont acheté entre deux dates",
    SEG_INACTIVE: "Sans achat depuis N jours (relance)",
    SEG_DEBT: "Avec une dette (rappel)",
    SEG_CATEGORY: "Ont acheté un produit d'une catégorie (suggestion)",
}
OPT_OUT_FOOTER = "\n\nPour ne plus recevoir nos messages, répondez STOP."

DEFAULTS = {
    "messaging_country_code": "226",
    "messaging_cap_whatsapp": "100",      # envois WhatsApp par jour (modifiable ; au-delà, risque de signalements)
    "messaging_cap_email": "150",
    "messaging_min_gap_days": "3",        # pas deux messages au même client avant ce délai
    "messaging_email_delay": "8",         # secondes entre deux e-mails
    "messaging_smtp_host": "",
    "messaging_smtp_port": "465",
    "messaging_smtp_security": "ssl",     # ssl | starttls
    "messaging_smtp_user": "",
    "messaging_smtp_password": "",
    "messaging_from_name": "",
}


def cfg(key: str) -> str:
    return settings_service.get_setting(key, DEFAULTS.get(key, "")) or DEFAULTS.get(key, "")


def cfg_int(key: str) -> int:
    try:
        return max(0, int(float(cfg(key))))
    except ValueError:
        return int(DEFAULTS[key])


# --- numéros et liens --------------------------------------------------------------------------
def normalize_phone(raw: str, country_code: Optional[str] = None) -> Optional[str]:
    """Numéro au format international sans « + » (ex. 22670123456), ou None s'il est inutilisable."""
    text = (raw or "").strip()
    if not text:
        return None
    international = text.startswith("+") or text.startswith("00")
    digits = re.sub(r"\D", "", text)
    if text.startswith("00"):
        digits = digits[2:]
    cc = re.sub(r"\D", "", country_code or cfg("messaging_country_code")) or "226"
    if not international:
        if digits.startswith(cc) and len(digits) >= len(cc) + 8:
            pass
        else:
            digits = cc + digits.lstrip("0")
    return digits if 8 <= len(digits) <= 15 else None


def whatsapp_link(phone: str, text: str) -> str:
    number = normalize_phone(phone)
    if not number:
        raise ValueError("Numéro de téléphone invalide.")
    return f"https://wa.me/{number}?text={quote(text, safe='')}"


def valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", (value or "").strip()))


# --- destinataires ----------------------------------------------------------------------------------
@dataclass
class Recipient:
    id: int
    name: str
    phone: str
    email: str
    debt: float
    last_visit: str = ""
    last_product: str = ""     # dernier produit acheté
    suggestion: str = ""       # produit de la même catégorie, pas encore acheté


def find_recipients(segment: str, channel: str, *, start: Optional[datetime] = None, end: Optional[datetime] = None, days: int = 90,
                    respect_gap: bool = True, category_id: Optional[int] = None) -> List[Recipient]:
    """Clients du segment joignables par le canal, hors « ne plus contacter » et hors contactés récemment."""
    now = datetime.now()
    with session_scope() as session:
        q = select(Client).where(Client.no_marketing.is_(False)).order_by(Client.name)
        clients = list(session.scalars(q))
        last_sale = {cid: d for cid, d in session.execute(select(Sale.client_id, func.max(Sale.date)).where(
            Sale.client_id.is_not(None), Sale.status == "completed").group_by(Sale.client_id))}
        in_range: set = set()
        if segment == SEG_BOUGHT:
            if start is None or end is None or end <= start:
                raise ValueError("Choisissez une période valide.")
            in_range = {cid for (cid,) in session.execute(select(Sale.client_id).where(
                Sale.client_id.is_not(None), Sale.status == "completed", Sale.date >= start, Sale.date < end).distinct())}
        in_category: set = set()
        if segment == SEG_CATEGORY:
            if not category_id:
                raise ValueError("Choisissez une catégorie.")
            in_category = {cid for (cid,) in session.execute(select(Sale.client_id).join(SaleItem, SaleItem.sale_id == Sale.id).join(
                Product, Product.id == SaleItem.product_id).where(Sale.client_id.is_not(None), Sale.status == "completed",
                                                                  Product.category_id == category_id).distinct())}
        recent: set = set()
        gap = cfg_int("messaging_min_gap_days")
        if respect_gap and gap:
            recent = {cid for (cid,) in session.execute(select(MessageLog.client_id).where(
                MessageLog.channel == channel, MessageLog.status == SENT, MessageLog.sent_at >= now - timedelta(days=gap)).distinct())}
        out: List[Recipient] = []
        for c in clients:
            if segment == SEG_BOUGHT and c.id not in in_range:
                continue
            if segment == SEG_CATEGORY and c.id not in in_category:
                continue
            if segment == SEG_INACTIVE:
                last = last_sale.get(c.id)
                if last is None or last > now - timedelta(days=max(1, days)):
                    continue
            if segment == SEG_DEBT and float(c.debt or 0) <= 0:
                continue
            if c.id in recent:
                continue
            if channel == WHATSAPP and not (normalize_phone(c.phone) or normalize_phone(c.phone2)):
                continue
            if channel == EMAIL and not valid_email(c.email):
                continue
            out.append(Recipient(c.id, c.name, c.phone if normalize_phone(c.phone) else c.phone2, (c.email or "").strip(), float(c.debt or 0), c.last_visit or ""))
        return out


def render(template: str, r: Recipient, shop_name: str = "", currency: str = "FCFA", footer: bool = True) -> str:
    first = (r.name or "").split()[0] if (r.name or "").strip() else ""
    values = {"nom": r.name, "prenom": first, "entreprise": shop_name, "dette": f"{r.debt:,.0f} {currency}".replace(",", " "),
              "dernier_achat": r.last_product, "suggestion": r.suggestion}
    text = re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), template or "")
    return text.rstrip() + (OPT_OUT_FOOTER if footer else "")


PRODUCT_VARS = ("{dernier_achat}", "{suggestion}")


def uses_products(template: str) -> bool:
    return any(v in (template or "") for v in PRODUCT_VARS)


def enrich_products(recipients: List[Recipient]) -> List[Recipient]:
    """Renseigne le dernier produit acheté et un produit similaire (même catégorie, jamais acheté, disponible, le plus vendu)."""
    from app.models.product import Product
    from app.models.sale import SaleItem

    with session_scope() as session:
        sold = {pid: float(q or 0) for pid, q in session.execute(
            select(SaleItem.product_id, func.sum(SaleItem.quantity)).where(SaleItem.product_id.is_not(None)).group_by(SaleItem.product_id))}
        products = list(session.scalars(select(Product).where(Product.is_active.is_(True))))
        by_cat: dict = {}
        for p in sorted(products, key=lambda p: -sold.get(p.id, 0.0)):
            if p.category_id is not None and (float(p.quantity or 0) > 0 or p.sell_without_stock):
                by_cat.setdefault(p.category_id, []).append(p)
        cat_of = {p.id: p.category_id for p in products}
        for r in recipients:
            rows = list(session.execute(
                select(SaleItem.product_id, SaleItem.product_name).join(Sale, Sale.id == SaleItem.sale_id)
                .where(Sale.client_id == r.id, Sale.status == "completed").order_by(Sale.date.desc(), SaleItem.id)))
            if not rows:
                continue
            r.last_product = next((n for _pid, n in rows if (n or "").strip()), "")
            bought = {pid for pid, _n in rows if pid is not None}
            first_pid = next((pid for pid, _n in rows if pid is not None), None)
            cat = cat_of.get(first_pid)
            if cat is not None:
                pick = next((p for p in by_cat.get(cat, []) if p.id not in bought), None)
                r.suggestion = pick.name if pick else ""
    return recipients


def drop_incomplete(recipients: List[Recipient], template: str) -> tuple:
    """Retire ceux pour qui une variable produit du message n'a pas de valeur (évite « vous avez acheté  »)."""
    keep, dropped = [], 0
    for r in recipients:
        if ("{dernier_achat}" in template and not r.last_product) or ("{suggestion}" in template and not r.suggestion):
            dropped += 1
        else:
            keep.append(r)
    return keep, dropped


TEMPLATES = {
    "Bonne fête": "Bonjour {prenom}, toute l'équipe de {entreprise} vous souhaite une très bonne fête ! Merci pour votre fidélité.",
    "Merci pour votre achat": "Bonjour {prenom}, merci d'avoir acheté chez {entreprise}. Nous espérons que {dernier_achat} vous donne entière satisfaction. À très bientôt !",
    "Produit similaire": "Bonjour {prenom}, vous avez acheté {dernier_achat} chez {entreprise}. Nous avons aussi {suggestion} qui pourrait vous plaire. Passez nous voir !",
    "Nouveautés": "Bonjour {prenom}, de nouveaux articles viennent d'arriver chez {entreprise}. Venez les découvrir !",
    "Rappel de dette": "Bonjour {prenom}, petit rappel : il reste {dette} à régler chez {entreprise}. Merci de passer quand vous pouvez.",
}


def save_limits(*, cap_whatsapp: int, cap_email: int, gap_days: int) -> None:
    settings_service.set_setting("messaging_cap_whatsapp", str(max(1, int(cap_whatsapp))))
    settings_service.set_setting("messaging_cap_email", str(max(1, int(cap_email))))
    settings_service.set_setting("messaging_min_gap_days", str(max(0, int(gap_days))))


# --- journal et plafonds ---------------------------------------------------------------------------
def log(client_id: Optional[int], channel: str, status: str, campaign: str = "", detail: str = "") -> None:
    with session_scope() as session:
        session.add(MessageLog(client_id=client_id, channel=channel, campaign=campaign[:120], status=status, detail=detail[:500]))


def sent_today(channel: str) -> int:
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    with session_scope() as session:
        return int(session.scalar(select(func.count()).select_from(MessageLog).where(
            MessageLog.channel == channel, MessageLog.status == SENT, MessageLog.sent_at >= start)) or 0)


def remaining_today(channel: str) -> int:
    cap = cfg_int("messaging_cap_whatsapp" if channel == WHATSAPP else "messaging_cap_email")
    return max(0, cap - sent_today(channel))


def opt_out(client_id: int) -> None:
    with session_scope() as session:
        c = session.get(Client, client_id)
        if c is not None:
            c.no_marketing = True


# --- e-mail ---------------------------------------------------------------------------------------------
def email_configured() -> bool:
    return bool(cfg("messaging_smtp_host").strip() and cfg("messaging_smtp_user").strip() and cfg("messaging_smtp_password"))


def save_email_config(*, host: str, port: int, security: str, user: str, password: str, from_name: str) -> None:
    if security not in ("ssl", "starttls"):
        raise ValueError("Sécurité inconnue.")
    for key, value in (("messaging_smtp_host", host.strip()), ("messaging_smtp_port", str(int(port))), ("messaging_smtp_security", security),
                       ("messaging_smtp_user", user.strip()), ("messaging_smtp_password", password), ("messaging_from_name", from_name.strip())):
        settings_service.set_setting(key, value)


def smtp_send(to: str, subject: str, body: str) -> None:
    host, port = cfg("messaging_smtp_host").strip(), cfg_int("messaging_smtp_port") or 465
    user, password = cfg("messaging_smtp_user").strip(), cfg("messaging_smtp_password")
    msg = EmailMessage()
    msg["From"] = f"{cfg('messaging_from_name')} <{user}>" if cfg("messaging_from_name") else user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    context = ssl.create_default_context()
    if cfg("messaging_smtp_security") == "starttls":
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
            server.login(user, password)
            server.send_message(msg)


def send_email_campaign(recipients: List[Recipient], subject: str, template: str, *, campaign: str, shop_name: str = "", currency: str = "FCFA",
                        footer: bool = True, sender: Optional[Callable[[str, str, str], None]] = None, delay: Optional[float] = None,
                        progress: Optional[Callable[[int, int, Recipient, str], None]] = None,
                        should_stop: Optional[Callable[[], bool]] = None, sleep: Callable[[float], None] = time.sleep) -> dict:
    """Envoie un e-mail à chacun, l'un après l'autre, avec un délai ; s'arrête au plafond quotidien ou sur demande."""
    if not (subject or "").strip():
        raise ValueError("Donnez un objet à l'e-mail.")
    if not (template or "").strip():
        raise ValueError("Le message est vide.")
    send = sender or smtp_send
    if sender is None and not email_configured():
        raise ValueError("Configurez d'abord le compte e-mail d'envoi.")
    pause = float(cfg("messaging_email_delay")) if delay is None else delay
    result = {"sent": 0, "failed": 0, "stopped": False, "capped": False}
    total = len(recipients)
    for i, r in enumerate(recipients, 1):
        if should_stop and should_stop():
            result["stopped"] = True
            break
        if remaining_today(EMAIL) <= 0:
            result["capped"] = True
            break
        try:
            send(r.email, subject.strip(), render(template, r, shop_name, currency, footer))
            log(r.id, EMAIL, SENT, campaign)
            result["sent"] += 1
            status = "envoyé"
        except Exception as exc:  # réseau, authentification, adresse refusée…
            log(r.id, EMAIL, FAILED, campaign, str(exc))
            result["failed"] += 1
            status = f"échec : {exc}"
        if progress:
            progress(i, total, r, status)
        if i < total and pause > 0:
            sleep(pause)
    return result
