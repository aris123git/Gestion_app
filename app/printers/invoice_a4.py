"""Facture A4 portrait (210 × 297 mm), page remplie, plusieurs modèles.

Le modèle et la taille de police se choisissent dans Paramètres → Apparence :
- ``invoice_style``     : identifiant d'un modèle de ``INVOICE_STYLES``
- ``invoice_font_size`` : taille du texte du tableau (pt), 7 à 20

Les modèles sont dessinés avec ReportLab (aucun fichier image externe).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, 
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app import config
from app.services import settings_service
from app.utils.helpers import format_amount, format_money, format_quantity

logger = logging.getLogger(__name__)

PAGE_W, PAGE_H = A4  # portrait : 210 × 297 mm
# Dimensions « virtuelles » du dessin des décors : modifiées le temps de la
# construction d'un PDF en demi-A4 (voir build_invoice_a4), puis restaurées.
_REAL_A4 = (PAGE_W, PAGE_H)

SETTING_FORMAT = "invoice_format"
FORMAT_A4 = "a4"
FORMAT_HALF = "demi_a4"  # A4 coupé en deux : 210 × 148,5 mm
HALF_H = 148.5 * mm
HALF_K = 0.45  # échelle du dessin en demi-A4 (en-tête / pied plus compacts)
INVOICE_FORMATS = (
    (FORMAT_A4, "A4 (page entière, 210 × 297 mm)"),
    (FORMAT_HALF, "A4 coupé en deux (210 × 148,5 mm)"),
)


SETTING_FILL_EMPTY = "invoice_fill_empty"


def get_fill_empty() -> bool:
    """True : ajoute des lignes vides pour remplir la page. Défaut : False (aucune ligne sans donnée)."""
    return settings_service.get_setting(SETTING_FILL_EMPTY, "0").strip() == "1"


def get_format() -> str:
    value = settings_service.get_setting(SETTING_FORMAT, FORMAT_A4).strip()
    return value if value in {f for f, _ in INVOICE_FORMATS} else FORMAT_A4
MARGIN = 14 * mm

SETTING_STYLE = "invoice_style"
SETTING_FONT = "invoice_font_size"
DEFAULT_STYLE = "recu"
DEFAULT_FONT = 10
MIN_FONT, MAX_FONT = 7, 20


@dataclass(frozen=True)
class InvoiceStyle:
    id: str
    label: str
    layout: str  # recu | vagues | moderne | diagonal
    primary: str
    light: str
    dark: str = "#0f172a"


INVOICE_STYLES: tuple[InvoiceStyle, ...] = (
    InvoiceStyle("recu", "Reçu classique — bleu marine", "recu", "#1e1b8f", "#eef0fb"),
    InvoiceStyle("recu_bordeaux", "Reçu classique — bordeaux", "recu", "#8b1a2b", "#f8e9ec"),
    InvoiceStyle("vagues", "Vagues — bleu", "vagues", "#1473b8", "#e6f1fa"),
    InvoiceStyle("vagues_vert", "Vagues — vert", "vagues", "#15803d", "#e6f4ea"),
    InvoiceStyle("moderne_bleu", "Moderne — bleu", "moderne", "#1f6fa8", "#eef4f9"),
    InvoiceStyle("moderne_orange", "Moderne — orange", "moderne", "#c8714f", "#faf0ea"),
    InvoiceStyle("diagonal_bleu", "Bandeau diagonal — bleu-gris", "diagonal", "#a9b9cc", "#dfe7f0"),
    InvoiceStyle("diagonal_beige", "Bandeau diagonal — beige", "diagonal", "#b59c85", "#efe5db"),
    # Modèles fidèles aux fichiers d'origine (fond vectoriel + polices du modèle)
    InvoiceStyle("services_bleu", "Services (vagues, fidèle au modèle) — bleu", "tpl_services", "#7fc5ff", "#ffffff"),
    InvoiceStyle("services_vert", "Services (vagues, fidèle au modèle) — vert", "tpl_services", "#7fffb0", "#ffffff"),
    InvoiceStyle("medical_bleu", "Médical (hexagones, fidèle au modèle) — bleu", "tpl_medical", "#0054ae", "#ffffff"),
    InvoiceStyle("medical_vert", "Médical (hexagones, fidèle au modèle) — vert", "tpl_medical", "#00ae5a", "#ffffff"),
)
_STYLES_BY_ID = {s.id: s for s in INVOICE_STYLES}


def get_style(style_id: str | None = None) -> InvoiceStyle:
    key = (style_id or settings_service.get_setting(SETTING_STYLE, DEFAULT_STYLE)).strip()
    return _STYLES_BY_ID.get(key, _STYLES_BY_ID[DEFAULT_STYLE])


def _mix(hex_color: str, with_white: float) -> str:
    """Éclaircit une couleur (0 = inchangée, 1 = blanc)."""
    c = HexColor(hex_color)
    r, g, b = (c.red + (1 - c.red) * with_white, c.green + (1 - c.green) * with_white, c.blue + (1 - c.blue) * with_white)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def _is_dark(hex_color: str) -> bool:
    c = HexColor(hex_color)
    return (0.299 * c.red + 0.587 * c.green + 0.114 * c.blue) < 0.55


def text_on(hex_color: str):
    """Couleur de texte lisible (blanc ou foncé) sur un fond de cette couleur."""
    return colors.white if _is_dark(hex_color) else HexColor("#1f2937")


def get_font_size() -> int:
    try:
        value = int(float(settings_service.get_setting(SETTING_FONT, str(DEFAULT_FONT))))
    except (TypeError, ValueError):
        value = DEFAULT_FONT
    return max(MIN_FONT, min(MAX_FONT, value))


# ── Montant en lettres (français) ────────────────────────────────────────────

_UNITS = [
    "zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
    "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize",
    "dix-sept", "dix-huit", "dix-neuf",
]
_TENS = ["", "", "vingt", "trente", "quarante", "cinquante", "soixante"]


def _below_100(n: int) -> str:
    if n < 20:
        return _UNITS[n]
    if n < 70:
        tens, unit = divmod(n, 10)
        if unit == 0:
            return _TENS[tens]
        return f"{_TENS[tens]}-et-un" if unit == 1 else f"{_TENS[tens]}-{_UNITS[unit]}"
    if n < 80:
        rest = n - 60
        return "soixante-et-onze" if rest == 11 else f"soixante-{_UNITS[rest]}"
    rest = n - 80
    return "quatre-vingts" if rest == 0 else f"quatre-vingt-{_UNITS[rest]}"


def _below_1000(n: int, final: bool) -> str:
    hundreds, rest = divmod(n, 100)
    parts: list[str] = []
    if hundreds:
        if hundreds == 1:
            parts.append("cent")
        else:
            parts.append(f"{_UNITS[hundreds]} cent" + ("s" if rest == 0 and final else ""))
    if rest:
        parts.append(_below_100(rest))
    return " ".join(parts)


def number_to_words_fr(value: int) -> str:
    """Nombre entier -> lettres (ex. 14000 -> « quatorze mille »)."""
    value = int(value)
    if value == 0:
        return "zéro"
    if value < 0:
        return "moins " + number_to_words_fr(-value)
    groups = [
        (1_000_000_000, "milliard"),
        (1_000_000, "million"),
        (1_000, "mille"),
    ]
    parts: list[str] = []
    for size, name in groups:
        count, value = divmod(value, size)
        if not count:
            continue
        if name == "mille":
            parts.append("mille" if count == 1 else f"{_below_1000(count, False)} mille")
        else:
            plural = "s" if count > 1 else ""
            parts.append(f"{_below_1000(count, True)} {name}{plural}")
    if value:
        parts.append(_below_1000(value, True))
    return " ".join(parts)


def amount_in_words(amount: float, currency: str) -> str:
    whole = int(round(float(amount)))
    text = number_to_words_fr(whole)
    unit = "francs CFA" if (currency or "").upper() in {"FCFA", "CFA", "XOF", "F CFA"} else currency
    return f"{text[:1].upper()}{text[1:]} {unit}"


# ── Données de la facture ────────────────────────────────────────────────────


def _vat_included(sale, items) -> tuple[float, float]:
    """(taux affiché, montant de TVA incluse). Taxes produit prioritaires."""
    total_vat = 0.0
    for item in items:
        rate = float(getattr(item, "tax_rate", 0) or 0)
        if rate > 0:
            total_vat += float(item.line_total or 0) * rate / (100 + rate)
    if total_vat > 0:
        return 0.0, round(total_vat, 3)
    rate = settings_service.get_vat_rate()
    if rate > 0:
        return rate, round(float(sale.total or 0) * rate / (100 + rate), 3)
    return 0.0, 0.0


def _cashier(sale) -> str:
    """Nom du caissier (jamais d'erreur, même si la session est fermée)."""
    try:
        name = getattr(sale, "cashier_name", "") or ""
    except Exception:
        name = ""
    return "" if name in ("", "—") else str(name)


from app.services.invoice_numbering import invoice_number  # noqa: E402


def client_refs(sale) -> dict:
    """Références du client de la vente : nom, contact(s), adresse, e-mail.

    Lit ``sale.client`` (fiche client) ; à défaut, les attributs simples
    ``client_name`` / ``client_phone`` / ``client_address`` (ventes de test).
    """
    try:
        client = getattr(sale, "client", None)
    except Exception:  # fiche non chargée (session fermée)
        client = None
    if client is not None:
        name = str(getattr(client, "name", "") or "")
        phones = [str(getattr(client, a, "") or "").strip() for a in ("phone", "phone2")]
        address = str(getattr(client, "address", "") or "").strip()
        email = str(getattr(client, "email", "") or "").strip()
    else:
        name = str(getattr(sale, "client_name", "") or "")
        phones = [str(getattr(sale, "client_phone", "") or "").strip()]
        address = str(getattr(sale, "client_address", "") or "").strip()
        email = str(getattr(sale, "client_email", "") or "").strip()
    return {
        "name": name.strip() or "Client de passage",
        "contact": " / ".join(p for p in phones if p),
        "address": address,
        "email": email,
        "known": client is not None or bool(name.strip() and name.strip() != "Client de passage"),
    }


def _line_cells(item, currency: str):
    quantity = float(item.quantity or 0)
    unit_price = float(item.unit_price or 0)
    line_total = float(item.line_total or 0)
    if abs(round(unit_price * quantity, 3) - line_total) > 0.01:
        return "—", "—"  # montant libre : pas de P.U. × quantité
    return format_quantity(quantity), format_amount(unit_price)


# ── Décors par modèle (en-tête / pied de page) ───────────────────────────────


def _draw_logo(canvas, shop, x, y, size) -> bool:
    logo = Path(str(getattr(shop, "logo_path", "") or ""))
    if logo.is_file():
        try:
            canvas.drawImage(
                str(logo), x, y, width=size, height=size,
                preserveAspectRatio=True, mask="auto", anchor="c",
            )
            return True
        except Exception:
            logger.debug("Logo facture ignoré.", exc_info=True)
    return False


def _contact_lines(shop) -> list[str]:
    lines = []
    if shop.address:
        lines.append(str(shop.address))
    phones = " / ".join(p for p in [str(shop.phone or "").strip()] if p)
    if phones:
        lines.append(f"Tél. {phones}")
    if shop.email:
        lines.append(str(shop.email))
    return lines


def _fit(canvas, text, font, size, max_width):
    while size > 6 and canvas.stringWidth(text, font, size) > max_width:
        size -= 0.5
    return size


def _decor_recu(canvas, ctx):
    st, shop = ctx["style"], ctx["shop"]
    primary = HexColor(st.primary)
    top = PAGE_H - 12 * mm
    canvas.setFillColor(primary)
    canvas.setFont("Helvetica-Bold", 26)
    canvas.drawString(MARGIN, top - 11 * mm, "FACTURE")
    canvas.setFont("Helvetica-Bold", 15)
    canvas.drawString(MARGIN, top - 21 * mm, f"N° {ctx['number']}")
    sep_x = MARGIN + 58 * mm
    canvas.setStrokeColor(primary)
    canvas.setLineWidth(0.8)
    canvas.line(sep_x, top - 24 * mm, sep_x, top)
    cx = (sep_x + PAGE_W - MARGIN) / 2
    name = str(shop.name or "Commerce").upper()
    size = _fit(canvas, name, "Helvetica-Bold", 20, PAGE_W - MARGIN - sep_x - 6 * mm)
    canvas.setFont("Helvetica-Bold", size)
    canvas.drawCentredString(cx, top - 9 * mm, name)
    canvas.setFillColor(HexColor("#475569"))
    y = top - 15 * mm
    for line in _contact_lines(shop)[:3]:
        canvas.setFont("Helvetica", 9)
        canvas.drawCentredString(cx, y, line)
        y -= 4.6 * mm
    canvas.setStrokeColor(primary)
    canvas.setLineWidth(1.6)
    canvas.line(MARGIN, top - 29 * mm, PAGE_W - MARGIN, top - 29 * mm)
    # Pied
    canvas.setLineWidth(0.8)
    canvas.line(MARGIN, 18 * mm, PAGE_W - MARGIN, 18 * mm)
    canvas.setFillColor(HexColor("#475569"))
    canvas.setFont("Helvetica-Oblique", 9)
    canvas.drawCentredString(PAGE_W / 2, 11 * mm, ctx["footer"])


def _wave(canvas, y_base, height, up: bool, color):
    """Bande ondulée pleine largeur (haut si up=False, bas si up=True)."""
    canvas.setFillColor(color)
    p = canvas.beginPath()
    w = PAGE_W
    if not up:  # en-tête : bord inférieur ondulé
        p.moveTo(0, PAGE_H)
        p.lineTo(0, y_base)
        p.curveTo(w * 0.25, y_base - height * 0.55, w * 0.5, y_base + height * 0.15, w * 0.72, y_base - height * 0.1)
        p.curveTo(w * 0.86, y_base - height * 0.25, w * 0.95, y_base - height * 0.05, w, y_base + height * 0.1)
        p.lineTo(w, PAGE_H)
    else:  # pied : bord supérieur ondulé
        p.moveTo(0, 0)
        p.lineTo(0, y_base)
        p.curveTo(w * 0.28, y_base + height * 0.55, w * 0.5, y_base - height * 0.2, w * 0.74, y_base + height * 0.12)
        p.curveTo(w * 0.88, y_base + height * 0.28, w * 0.96, y_base + height * 0.05, w, y_base - height * 0.05)
        p.lineTo(w, 0)
    p.close()
    canvas.drawPath(p, stroke=0, fill=1)


def _decor_vagues(canvas, ctx):
    st, shop = ctx["style"], ctx["shop"]
    primary = HexColor(st.primary)
    light = HexColor(_mix(st.primary, 0.45))
    _wave(canvas, PAGE_H - 46 * mm, 20 * mm, False, light)
    _wave(canvas, PAGE_H - 40 * mm, 18 * mm, False, primary)
    # Logo dans un disque blanc
    cx, cy, r = MARGIN + 12 * mm, PAGE_H - 22 * mm, 12 * mm
    canvas.setFillColor(colors.white)
    canvas.circle(cx, cy, r, stroke=0, fill=1)
    if not _draw_logo(canvas, shop, cx - r + 2 * mm, cy - r + 2 * mm, 2 * r - 4 * mm):
        canvas.setFillColor(primary if _is_dark(st.primary) else HexColor("#1f2937"))
        canvas.setFont("Helvetica-Bold", 22)
        initial = (str(shop.name or "C").strip()[:1] or "C").upper()
        canvas.drawCentredString(cx, cy - 2.7 * mm, initial)
    name = str(shop.name or "Commerce")
    canvas.setFillColor(text_on(st.primary))
    size = _fit(canvas, name, "Helvetica-Bold", 13, 62 * mm)
    canvas.setFont("Helvetica-Bold", size)
    canvas.drawString(cx + r + 4 * mm, cy - 1.5 * mm, name)
    canvas.setFont("Helvetica-Bold", 34)
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 27 * mm, "FACTURE")
    # Pied
    _wave(canvas, 20 * mm, 14 * mm, True, light)
    _wave(canvas, 14 * mm, 12 * mm, True, primary)
    canvas.setFillColor(text_on(st.primary))
    canvas.setFont("Helvetica", 9)
    lines = _contact_lines(shop)
    canvas.drawString(MARGIN, 8.5 * mm, "  ·  ".join(lines)[:110])
    canvas.setFont("Helvetica-Oblique", 9)
    canvas.drawRightString(PAGE_W - MARGIN, 8.5 * mm, ctx["footer"][:110])


def _decor_moderne(canvas, ctx):
    st, shop = ctx["style"], ctx["shop"]
    primary = HexColor(st.primary)
    top = PAGE_H - 14 * mm
    x = MARGIN
    if _draw_logo(canvas, shop, x, top - 14 * mm, 14 * mm):
        x += 17 * mm
    name = str(shop.name or "Commerce")
    size = _fit(canvas, name.upper(), "Helvetica-Bold", 17, 80 * mm)
    canvas.setFillColor(primary)
    canvas.setFont("Helvetica-Bold", size)
    canvas.drawString(x, top - 7 * mm, name.upper())
    # Filet dégradé simulé (sombre puis couleur)
    canvas.setStrokeColor(HexColor("#222222"))
    canvas.setLineWidth(1.4)
    canvas.line(MARGIN, top - 17 * mm, MARGIN + 60 * mm, top - 17 * mm)
    canvas.setStrokeColor(primary)
    canvas.setLineWidth(0.8)
    canvas.line(MARGIN + 60 * mm, top - 17 * mm, PAGE_W - MARGIN, top - 17 * mm)
    canvas.setFillColor(HexColor("#475569"))
    y = top - 3 * mm
    for line in _contact_lines(shop)[:3]:
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(PAGE_W - MARGIN, y, line)
        y -= 4.4 * mm
    # Titre
    canvas.setFillColor(primary)
    canvas.setFont("Helvetica-Bold", 30)
    canvas.drawRightString(PAGE_W - MARGIN, top - 38 * mm, "FACTURE")
    # Pied : bande sombre + trapèzes de couleur
    canvas.setFillColor(HexColor("#2b2b2b"))
    canvas.rect(0, 0, PAGE_W, 9 * mm, stroke=0, fill=1)
    canvas.setFillColor(primary)
    p = canvas.beginPath()
    p.moveTo(18 * mm, 9 * mm)
    p.lineTo(24 * mm, 14 * mm)
    p.lineTo(PAGE_W / 2 - 4 * mm, 14 * mm)
    p.lineTo(PAGE_W / 2 + 2 * mm, 9 * mm)
    p.close()
    canvas.drawPath(p, stroke=0, fill=1)
    p = canvas.beginPath()
    p.moveTo(PAGE_W / 2 + 6 * mm, 9 * mm)
    p.lineTo(PAGE_W / 2 + 12 * mm, 14 * mm)
    p.lineTo(PAGE_W - 24 * mm, 14 * mm)
    p.lineTo(PAGE_W - 18 * mm, 9 * mm)
    p.close()
    canvas.drawPath(p, stroke=0, fill=1)
    canvas.setFillColor(HexColor("#555555"))
    canvas.setFont("Helvetica-Oblique", 9)
    canvas.drawCentredString(PAGE_W / 2, 17 * mm, ctx["footer"])


def _decor_diagonal(canvas, ctx):
    st, shop = ctx["style"], ctx["shop"]
    band = HexColor(st.primary)
    h = 44 * mm
    canvas.setFillColor(band)
    p = canvas.beginPath()
    p.moveTo(0, PAGE_H)
    p.lineTo(PAGE_W, PAGE_H)
    p.lineTo(PAGE_W, PAGE_H - h)
    p.lineTo(0, PAGE_H - h)
    p.close()
    canvas.drawPath(p, stroke=0, fill=1)
    # Bandes blanches diagonales
    for x0, wd, tone in ((70, 5, "#ffffff"), (80, 2.2, "#e9e4dc"), (86, 1.4, "#cfd6de")):
        canvas.setFillColor(HexColor(tone))
        p = canvas.beginPath()
        p.moveTo((x0 - 14) * mm, PAGE_H)
        p.lineTo((x0 - 14 + wd) * mm, PAGE_H)
        p.lineTo((x0 + 14 + wd) * mm, PAGE_H - h)
        p.lineTo((x0 + 14) * mm, PAGE_H - h)
        p.close()
        canvas.drawPath(p, stroke=0, fill=1)
    on_band = HexColor("#ffffff") if _is_dark(st.primary) else HexColor("#2b2b2b")
    canvas.setFillColor(on_band)
    canvas.setFont("Helvetica-Bold", 30)
    canvas.drawString(MARGIN, PAGE_H - 22 * mm, "FACTURE")
    name = str(shop.name or "Commerce").upper()
    size = _fit(canvas, name, "Helvetica-Bold", 13, 78 * mm)
    canvas.setFont("Helvetica-Bold", size)
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 15 * mm, name)
    canvas.setFont("Helvetica", 9)
    y = PAGE_H - 21 * mm
    for line in _contact_lines(shop)[:3]:
        canvas.drawRightString(PAGE_W - MARGIN, y, line)
        y -= 4.6 * mm
    # Pied
    canvas.setFillColor(HexColor("#2b2b2b"))
    canvas.rect(0, 0, PAGE_W, 5 * mm, stroke=0, fill=1)
    canvas.setFillColor(HexColor("#6b7280"))
    canvas.setFont("Helvetica-Oblique", 9)
    canvas.drawCentredString(PAGE_W / 2, 10 * mm, ctx["footer"])


_DECORS = {
    "recu": _decor_recu,
    "vagues": _decor_vagues,
    "moderne": _decor_moderne,
    "diagonal": _decor_diagonal,
}

# Hauteur réservée (mm) en haut / en bas de chaque page selon le modèle.
_ZONES = {
    "recu": (44, 24),
    "vagues": (54, 30),
    "moderne": (56, 24),
    "diagonal": (52, 18),
}


# ── Construction du PDF ──────────────────────────────────────────────────────


SETTING_SHOW_BANK = "invoice_show_bank"


def bank_text(setting: str = SETTING_SHOW_BANK) -> str:
    """« Banque : X — Compte : Y » si l'option ``setting`` est active (défaut : oui) et si renseigné."""
    if settings_service.get_setting(setting, "1").strip() != "1":
        return ""
    name = settings_service.get_setting("shop_bank_name", "").strip()
    number = settings_service.get_setting("shop_bank_account", "").strip()
    parts = [f"Banque : {name}" if name else "", f"Compte : {number}" if number else ""]
    return "  ·  ".join(p for p in parts if p)


def footer_with_bank(footer: str) -> str:
    bank = bank_text()
    return f"{footer}  ·  {bank}" if footer and bank else (bank or footer)


def build_invoice_a4(sale, shop=None, path: Path | None = None,
                     style_id: str | None = None, font_size: int | None = None,
                     fmt: str | None = None, fill_empty: bool | None = None) -> Path:
    """Génère la facture (A4 portrait, ou A4 coupé en deux) et retourne le PDF."""
    global PAGE_W, PAGE_H
    config.ensure_directories()
    shop = shop or settings_service.get_shop_info()
    currency = shop.currency or "FCFA"
    style = get_style(style_id)
    fs = max(MIN_FONT, min(MAX_FONT, int(font_size or get_font_size())))
    fmt = fmt if fmt in {f for f, _ in INVOICE_FORMATS} else get_format()
    half = fmt == FORMAT_HALF
    if half and style.layout.startswith("tpl_"):
        # Les modèles fidèles (Services, Médical) n'existent qu'en A4 entier.
        style = get_style("recu")
    k = HALF_K if half else 1.0
    real_w = _REAL_A4[0]
    real_h = HALF_H if half else _REAL_A4[1]
    tag = "demiA4" if half else "A4"

    if path is None:
        path = config.TICKET_DIR / f"{sale.ticket_number}_{tag}.pdf"
        if path.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = config.TICKET_DIR / f"{sale.ticket_number}_{tag}_{stamp}.pdf"
    path = Path(path)

    if style.layout.startswith("tpl_"):
        from app.printers.invoice_template import build_template_invoice

        return build_template_invoice(sale, shop, path, style.id, fs)

    number = invoice_number(sale)
    moment = sale.date or datetime.now()
    footer = footer_with_bank(str(shop.ticket_footer or "Merci pour votre confiance."))
    ctx = {"style": style, "shop": shop, "number": number, "footer": footer}
    top_mm, bottom_mm = (z * k for z in _ZONES[style.layout])
    decor = _DECORS[style.layout]
    margin = MARGIN * k

    def on_page(canvas, doc):
        canvas.saveState()
        if k != 1.0:
            canvas.scale(k, k)  # le décor est dessiné sur une page virtuelle plus grande
        decor(canvas, ctx)
        canvas.restoreState()

    frame_w = real_w - 2 * margin
    frame_h = real_h - (top_mm + bottom_mm) * mm
    frame = Frame(margin, bottom_mm * mm, frame_w, frame_h,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="body")
    doc = BaseDocTemplate(
        str(path), pagesize=(real_w, real_h), leftMargin=margin, rightMargin=margin,
        topMargin=top_mm * mm, bottomMargin=bottom_mm * mm,
        title=f"Facture {number}", author=str(shop.name or ""),
    )
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=on_page)])

    primary = HexColor(style.primary)
    light = HexColor(style.light)
    dark = HexColor(style.dark)
    muted = HexColor("#475569")
    # Texte du tableau = taille réglée ; le reste suit proportionnellement.
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=fs, leading=fs * 1.3, textColor=dark)
    body_b = ParagraphStyle("bodyb", parent=body, fontName="Helvetica-Bold")
    small = ParagraphStyle("small", parent=body, fontSize=max(7, fs - 1), leading=max(7, fs - 1) * 1.3, textColor=muted)
    right_b = ParagraphStyle("rb", parent=body_b, alignment=2)

    story = []

    # Bloc client / références
    refs_client = client_refs(sale)
    if style.layout == "recu":
        # Comme le reçu d'origine : « De : » puis Nom / Contact / Adresse.
        client_lines = [Paragraph("<b>De :</b>", ParagraphStyle("de", parent=body, fontSize=fs + 3, leading=(fs + 3) * 1.3, textColor=primary))]
        rows_c = [("Nom", refs_client["name"])]
        if refs_client["contact"]:
            rows_c.append(("Contact", refs_client["contact"]))
        if refs_client["address"]:
            rows_c.append(("Adresse", refs_client["address"]))
        if refs_client["email"]:
            rows_c.append(("E-mail", refs_client["email"]))
        ref_t = Table([[Paragraph(a, small), Paragraph(f"<b>{b}</b>" if a == "Nom" else b, body)] for a, b in rows_c], colWidths=[20 * mm, 78 * mm])
        ref_t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
        client_lines.append(ref_t)
    else:
        client_lines = [Paragraph("<b>Facturé à</b>", small)]
        client_lines.append(Paragraph(f"<b>{refs_client['name']}</b>", ParagraphStyle("c", parent=body, fontSize=fs + 2, leading=(fs + 2) * 1.3)))
        if refs_client["contact"]:
            client_lines.append(Paragraph(f"Contact : {refs_client['contact']}", small))
        if refs_client["address"]:
            client_lines.append(Paragraph(f"Adresse : {refs_client['address']}", small))
        if refs_client["email"]:
            client_lines.append(Paragraph(f"E-mail : {refs_client['email']}", small))
    refs = [
        Paragraph(f"<b>Facture N°</b> {number}", ParagraphStyle("r", parent=body, alignment=2)),
        Paragraph(f"<b>Date</b> {moment:%d/%m/%Y}  {moment:%H:%M}", ParagraphStyle("r2", parent=body, alignment=2)),
    ]
    if _cashier(sale):
        refs.append(Paragraph(f"<b>Caissier</b> {_cashier(sale)}", ParagraphStyle("r3", parent=body, alignment=2)))
    meta = Table([[client_lines, refs]], colWidths=[frame_w * 0.55, frame_w * 0.45])
    meta.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story += [meta, Spacer(1, 7 * mm * k)]

    # Tableau des lignes
    head = ["N°", "Désignation", "Qté", "Prix unitaire", "Total"]
    rows = [head]
    items = list(sale.items)
    for index, item in enumerate(items, start=1):
        qty_txt, pu_txt = _line_cells(item, currency)
        rows.append([
            str(index),
            Paragraph(str(item.product_name or ""), body),
            qty_txt, pu_txt, format_amount(float(item.line_total or 0)),
        ])
    col_w = [11 * mm, frame_w - 11 * mm - 22 * mm - 38 * mm - 40 * mm, 22 * mm, 38 * mm, 40 * mm]
    pad = max(1, fs * 0.12) if half else max(3, int(fs * 0.45))
    layout = style.layout

    def table_style(n_rows: int):
        cmds = [
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), fs),
            ("TEXTCOLOR", (0, 1), (-1, -1), dark),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]
        if layout == "recu":
            cmds += [
                ("BOX", (0, 0), (-1, -1), 1, primary), ("INNERGRID", (0, 0), (-1, -1), 0.6, primary),
                ("TEXTCOLOR", (0, 0), (-1, 0), primary), ("LINEBELOW", (0, 0), (-1, 0), 1.4, primary),
            ]
        elif layout == "vagues":
            cmds += [
                ("BACKGROUND", (0, 0), (-1, 0), primary), ("TEXTCOLOR", (0, 0), (-1, 0), text_on(style.primary)),
                ("LINEBELOW", (0, 1), (-1, -1), 0.5, HexColor("#cbd5e1")),
                ("ROUNDEDCORNERS", [8, 8, 0, 0]),
            ]
        elif layout == "moderne":
            cmds += [
                ("BOX", (0, 0), (-1, 0), 0.9, dark), ("TEXTCOLOR", (0, 0), (-1, 0), dark),
                ("LINEBELOW", (0, 1), (-1, -1), 0.8, HexColor("#8b8b8b")),
            ]
        else:  # diagonal : cellules colorées
            cmds += [
                ("BACKGROUND", (0, 0), (-1, 0), primary),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white if _is_dark(style.primary) else dark),
                ("BACKGROUND", (0, 1), (-1, -1), light),
                ("LINEBELOW", (0, 1), (-1, -1), 2.2, colors.white),
                ("LINEBELOW", (0, -1), (-1, -1), 1.4, dark),
            ]
        return TableStyle(cmds)

    # Totaux (hauteur connue pour remplir la page avant eux)
    totals = []
    discount = float(sale.discount or 0)
    totals.append(["Sous-total", format_money(sale.subtotal, currency)])
    if discount > 0:
        totals.append(["Remise", "- " + format_money(discount, currency)])
    rate, vat_amount = _vat_included(sale, items)
    total_label_row = len(totals)
    totals.append(["TOTAL", format_money(sale.total, currency)])
    if float(sale.amount_received or 0) > 0:
        totals.append(["Reçu", format_money(sale.amount_received, currency)])
        totals.append(["Monnaie rendue", format_money(sale.change_due, currency)])
    totals_t = Table(totals, colWidths=[44 * mm, 52 * mm])
    t_cmds = [
        ("FONTSIZE", (0, 0), (-1, -1), fs), ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("TEXTCOLOR", (0, 0), (-1, -1), dark),
        ("TOPPADDING", (0, 0), (-1, -1), 1 if half else 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1 if half else 2.5),
        ("FONTNAME", (0, total_label_row), (-1, total_label_row), "Helvetica-Bold"),
        ("FONTSIZE", (0, total_label_row), (-1, total_label_row), fs + 3),
        ("LINEABOVE", (0, total_label_row), (-1, total_label_row), 1.2, primary),
        ("TEXTCOLOR", (0, total_label_row), (-1, total_label_row), primary if layout != "diagonal" else dark),
    ]
    if layout == "vagues":
        t_cmds += [("BACKGROUND", (0, total_label_row), (-1, total_label_row), primary),
                   ("TEXTCOLOR", (0, total_label_row), (-1, total_label_row), text_on(style.primary))]
    totals_t.setStyle(TableStyle(t_cmds))

    # Bloc gauche du pied : arrêté + moyens de paiement
    left = []
    words = amount_in_words(float(sale.total or 0), currency)
    left.append(Paragraph(f"<b>Arrêtée la présente facture à la somme de</b><br/>{words} ({format_money(sale.total, currency)})", body))
    if sale.payments:
        left.append(Spacer(1, (1 if half else 3) * mm))
        left.append(Paragraph("<b>Méthode de paiement</b>", body))
        for pay in sale.payments:
            left.append(Paragraph(f"{pay.method} : {format_money(pay.amount, currency)}", small))
    sign = Paragraph(
        "<b>Le responsable</b>" if layout in ("recu", "moderne") else "<b>Signature</b>",
        ParagraphStyle("sg", parent=body, alignment=1),
    )
    bottom = Table([[left, [totals_t, Spacer(1, (2 if half else 6) * mm), sign]]], colWidths=[frame_w - 100 * mm, 100 * mm])
    bottom.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, 0), 8 * mm),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    # Pas de lignes vides : le tableau ne contient que les articles. Le bloc des
    # totaux est poussé en bas de page par un espace (la page reste équilibrée).
    _, meta_h = meta.wrap(frame_w, frame_h)
    _, bottom_h = bottom.wrap(frame_w, frame_h)
    reserve = meta_h + 7 * mm * k + bottom_h + 8 * mm * k + 4 * mm * k
    available = frame_h - reserve
    items_t = Table(rows, colWidths=col_w, repeatRows=1)
    items_t.setStyle(table_style(len(rows)))
    _, cur_h = items_t.wrap(frame_w, frame_h)
    fill = get_fill_empty() if fill_empty is None else bool(fill_empty)
    if fill and cur_h <= available:
        # Option « lignes vides » : complète le tableau jusqu'au bas de la page.
        probe = [""] * 5
        while True:
            trial_rows = rows + [probe]
            trial = Table(trial_rows, colWidths=col_w, repeatRows=1)
            trial.setStyle(table_style(len(trial_rows)))
            _, h = trial.wrap(frame_w, frame_h)
            if h > available:
                break
            rows = trial_rows
            items_t = trial
        _, cur_h = items_t.wrap(frame_w, frame_h)
    # Les totaux suivent directement la dernière ligne (sauf en mode « lignes vides »).
    gap = 8 * mm * k + (max(0.0, available - cur_h) if fill and cur_h <= available else 0.0)
    story += [items_t, Spacer(1, gap), KeepTogether([bottom])]

    saved = (PAGE_W, PAGE_H)
    PAGE_W, PAGE_H = real_w / k, real_h / k  # taille virtuelle utilisée par les décors
    try:
        doc.build(story)
    finally:
        PAGE_W, PAGE_H = saved
    return path
