"""Génération et impression des tickets thermiques (58 mm / 80 mm)
et factures demi-A4 (papier A4 coupé en deux).

Deux sorties sont proposées :

- ``render_ticket_text`` construit le ticket en texte monospace (aperçu et
  réimpression, largeur adaptée au format) ;
- ``print_ticket`` envoie le ticket à une imprimante ESC/POS (thermique)
  ou génère/imprime un PDF demi-A4 pour imprimante bureau.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from app import config
from app.services import settings_service
from app.utils.helpers import format_money, format_quantity

logger = logging.getLogger(__name__)


@dataclass
class PrintResult:
    """Résultat d'une tentative d'impression.

    - ``printed`` : True si les données ont bien été envoyées à une imprimante ;
    - ``file_path`` : chemin de la copie texte/PDF du ticket (toujours créée) ;
    - ``message`` : explication (utile en cas d'échec ou d'absence d'imprimante).
    """

    printed: bool
    file_path: Path
    message: str = ""

# Nombre de caractères par ligne selon la largeur du papier.
WIDTH_CHARS = {"58mm": 32, "80mm": 48, "demi-A4": 72}
PAPER_FORMATS = ("80mm", "58mm", "demi-A4")

# Compatibilité : anciens IDs ``ticket_layout`` (migrés vers la biblio designs).
TICKET_LAYOUT_CLASSIC = "classic"
TICKET_LAYOUT_COMPACT = "compact"
TICKET_LAYOUT_TABLE = "table"  # → design « terminal »
TICKET_LAYOUT_KITCHEN = "kitchen"  # → design « serveur »
TICKET_LAYOUTS = (
    TICKET_LAYOUT_CLASSIC,
    TICKET_LAYOUT_COMPACT,
    TICKET_LAYOUT_TABLE,
    TICKET_LAYOUT_KITCHEN,
)
TICKET_LAYOUT_LABELS = {
    TICKET_LAYOUT_CLASSIC: "Classique",
    TICKET_LAYOUT_COMPACT: "Compact",
    TICKET_LAYOUT_TABLE: "Terminal",
    TICKET_LAYOUT_KITCHEN: "Bon serveur",
}


def _line(char: str = "-", width: int = 32) -> str:
    return char * width


def _row(left: str, right: str, width: int) -> str:
    """Place ``left`` à gauche et ``right`` à droite sur une même ligne."""
    from app.printers.ticket.layout import row

    return row(left, right, width)


def _center(text: str, width: int) -> str:
    from app.printers.ticket.layout import center

    return center(text, width)


def _resolve_layout(layout: Optional[str] = None) -> str:
    """Résout l'ID de design client (compat. ancien ``ticket_layout``)."""
    from app.printers.ticket.registry import resolve_client_design_id

    return resolve_client_design_id(layout)


def render_ticket_text(
    sale,
    shop=None,
    paper: str = "80mm",
    layout: Optional[str] = None,
    *,
    design_id: Optional[str] = None,
    role: str = "client",
) -> str:
    """Construit le contenu texte d'un ticket à partir d'une vente ORM.

    Le rendu est délégué à ``app.printers.ticket`` (données → design → texte).
    ``layout`` reste accepté pour compatibilité (alias de ``design_id``).
    """
    from app.printers.half_a4_invoice import is_half_a4
    from app.printers.ticket.data import TicketData
    from app.printers.ticket.registry import get_design
    from app.printers.ticket.renderer import render_ticket_text_from_data

    shop = shop or settings_service.get_shop_info()
    did = design_id or layout
    resolved_role = role
    if did:
        design = get_design(did)
        if design.category == "kitchen":
            resolved_role = "kitchen"
    elif role == "client":
        # Si l'ancien réglage unique était « kitchen », le ticket client
        # standard utilise quand même le design client (classic) sauf
        # appel explicite role=kitchen.
        pass

    data = TicketData.from_sale(sale, shop)
    text = render_ticket_text_from_data(
        data, design_id=did, role=resolved_role, paper=paper
    )
    if is_half_a4(paper):
        # Préfixe facture pour l'aperçu texte demi-A4.
        width = WIDTH_CHARS.get("demi-A4", 72)
        header = _center("FACTURE", width) + "\n"
        footer = "\n" + _center("Format demi-A4 (210 × 148,5 mm)", width)
        text = header + text.rstrip("\n") + footer + "\n\n"
    return text


def save_ticket_file(
    sale,
    shop=None,
    paper: str = "80mm",
    *,
    design_id: Optional[str] = None,
    role: str = "client",
) -> Path:
    """Enregistre le ticket dans un fichier texte (repli sans imprimante)."""
    config.ensure_directories()
    content = render_ticket_text(
        sale, shop, paper, design_id=design_id, role=role
    )
    path = config.TICKET_DIR / f"{sale.ticket_number}.txt"
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = config.TICKET_DIR / f"{sale.ticket_number}_{stamp}.txt"
        counter = 1
        while path.exists():
            path = config.TICKET_DIR / f"{sale.ticket_number}_{stamp}_{counter}.txt"
            counter += 1
    path.write_text(content, encoding="utf-8")
    return path


# Nombre de lignes d'avance papier par défaut avant la coupe. Nécessaire pour
# que la fin du ticket dépasse la tête d'impression et le massicot.
DEFAULT_FEED_LINES = 5
# Mode de coupe par défaut : "full" (complète), "partial" (partielle) ou "none".
DEFAULT_CUT_MODE = "full"

_CUT_MODES = {"full": "FULL", "partial": "PART"}


@dataclass
class DiscoveredPrinter:
    """Imprimante vue sur le poste (pas stockée en base — détection live)."""

    name: str
    online: bool = True
    pending_deletion: bool = False


def list_printers_detailed() -> list[DiscoveredPrinter]:
    """Détecte les imprimantes **actuellement** installées sur le poste.

    Important : la base SQLite ne stocke **pas** un catalogue d'imprimantes.
    Seuls les noms choisis (`printer_name` / `invoice_printer_name`) y sont
    mémorisés. Cette fonction interroge Windows / CUPS à chaque appel.
    """
    found: list[DiscoveredPrinter] = []
    if sys.platform.startswith("win"):  # pragma: no cover - dépend de Windows
        found = _list_printers_windows()
    else:
        found = _list_printers_posix()

    # Déduplique, ignore les files en cours de suppression.
    seen: set[str] = set()
    unique: list[DiscoveredPrinter] = []
    for item in found:
        key = (item.name or "").strip()
        if not key or item.pending_deletion:
            continue
        low = key.lower()
        if low in seen:
            continue
        seen.add(low)
        unique.append(DiscoveredPrinter(name=key, online=item.online))
    unique.sort(
        key=lambda p: (
            0 if is_likely_thermal_printer(p.name) else 1,
            0 if p.online else 1,
            p.name.lower(),
        )
    )
    return unique


def list_printers(*, include_offline: bool = True) -> list[str]:
    """Noms des imprimantes installées sur le poste (détection live).

    Les imprimantes ticket (POS 80C…) sont listées en premier.
    Les files désinstallées / en suppression ne sont pas renvoyées.
    """
    return [
        p.name
        for p in list_printers_detailed()
        if include_offline or p.online
    ]


def _list_printers_windows() -> list[DiscoveredPrinter]:  # pragma: no cover
    try:
        import win32print
    except Exception:
        return []

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    # Level 2 : Attributes + Status (hors ligne / suppression).
    try:
        raw = win32print.EnumPrinters(flags, None, 2)
    except Exception:
        try:
            raw = win32print.EnumPrinters(flags)
            return [
                DiscoveredPrinter(name=printer[2], online=True)
                for printer in raw
                if printer and printer[2]
            ]
        except Exception:
            return []

    pending_deletion = 0x00000004
    status_offline = 0x00000080
    status_not_available = 0x00001000
    attr_work_offline = 0x00000400

    out: list[DiscoveredPrinter] = []
    for printer in raw or []:
        try:
            name = (printer.get("pPrinterName") or printer.get("Name") or "").strip()
        except AttributeError:
            # Ancien format tuple
            name = ""
            if isinstance(printer, (tuple, list)) and len(printer) > 2:
                name = str(printer[2] or "").strip()
        if not name:
            continue
        try:
            status = int(printer.get("Status", 0) or 0)
            attrs = int(printer.get("Attributes", 0) or 0)
        except Exception:
            status, attrs = 0, 0
        pending = bool(status & pending_deletion)
        offline = bool(
            (attrs & attr_work_offline)
            or (status & status_offline)
            or (status & status_not_available)
        )
        out.append(
            DiscoveredPrinter(
                name=name,
                online=not offline,
                pending_deletion=pending,
            )
        )
    return out


def _list_printers_posix() -> list[DiscoveredPrinter]:
    try:
        proc = subprocess.run(
            ["lpstat", "-a"],
            capture_output=True,
            timeout=5,
            text=True,
            check=False,
        )
    except Exception:
        return []
    out: list[DiscoveredPrinter] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        name = line.split()[0]
        # lpstat -a : files acceptant des jobs (= actives).
        out.append(DiscoveredPrinter(name=name, online=True))
    return out


def default_printer() -> str:
    """Retourne le nom de l'imprimante par défaut du système."""
    if sys.platform.startswith("win"):  # pragma: no cover - dépend de Windows
        try:
            import win32print

            return win32print.GetDefaultPrinter() or ""
        except Exception:
            return ""
    try:
        proc = subprocess.run(
            ["lpstat", "-d"], capture_output=True, timeout=5, text=True, check=False
        )
        if proc.returncode != 0:
            return ""
        # Exemple CUPS : "system default destination: Epson_TM_T20"
        marker = ":"
        line = proc.stdout.strip()
        if marker in line:
            return line.split(marker, 1)[1].strip()
    except Exception:
        return ""
    return ""


def is_device_path(name: str) -> bool:
    """True si ``name`` ressemble à un chemin de périphérique (/dev/…, \\\\…)."""
    name = (name or "").strip()
    return bool(name) and ("/" in name or name.startswith("\\"))


def normalize_printer_key(name: str) -> str:
    """Normalise un nom pour comparaison souple (POS 80C ↔ POS-80C ↔ POS80C)."""
    import re

    text = (name or "").strip().lower()
    # Enlever suffixes Windows fréquents.
    for suffix in (
        " (copie 1)",
        " (copy 1)",
        " (redirected",
    ):
        if suffix in text:
            text = text.split(suffix, 1)[0]
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


# Motifs typiques d'imprimantes ticket (noms Windows courants).
_THERMAL_NAME_HINTS = (
    "pos",
    "tm-",
    "tm_",
    "tmt",
    "epson",
    "xp-",
    "xp_",
    "xprinter",
    "gp-",
    "gprinter",
    "receipt",
    "ticket",
    "thermal",
    "thermique",
    "80c",
    "80mm",
    "58mm",
    "58c",
    "rongta",
    "bixolon",
    "star ",
    "tsp",
    "citizen",
)


_VIRTUAL_PRINTER_HINTS = (
    "microsoft print to pdf",
    "microsoft xps",
    "onenote",
    "fax",
    "adobe pdf",
    "foxit",
    "send to",
    "anydesk",
    "pdf creator",
    "bullzip",
    "cutepdf",
    "print to pdf",
    "document writer",
    "root printer",  # CUPS placeholder
)


def is_virtual_printer(name: str) -> bool:
    """True pour PDF / Fax / XPS… (pas une imprimante ticket physique)."""
    low = (name or "").strip().lower()
    if not low:
        return False
    return any(hint in low for hint in _VIRTUAL_PRINTER_HINTS)


def dedupe_printer_names(names: list[str]) -> list[str]:
    """Une seule entrée par file réelle (POS 80C ≈ POS-80C ≈ POS80C).

    Préfère le nom sans suffixe « copie », puis le plus court.
    """
    best: dict[str, str] = {}
    for name in names or []:
        raw = (name or "").strip()
        if not raw:
            continue
        key = normalize_printer_key(raw)
        if not key:
            continue
        prev = best.get(key)
        if prev is None:
            best[key] = raw
            continue
        prev_low = prev.lower()
        new_low = raw.lower()
        prev_copy = "copie" in prev_low or "copy" in prev_low
        new_copy = "copie" in new_low or "copy" in new_low
        if prev_copy and not new_copy:
            best[key] = raw
        elif new_copy and not prev_copy:
            continue
        elif len(raw) < len(prev):
            best[key] = raw
    out = list(best.values())
    out.sort(key=lambda n: (0 if is_likely_thermal_printer(n) else 1, n.lower()))
    return out


def printers_for_ticket_combo(names: list[str]) -> list[str]:
    """Noms à proposer pour l'imprimante **ticket** (thermique).

    Exclut PDF/Fax/XPS. S'il existe au moins une thermique (POS, Epson TM…),
    seules celles-ci sont proposées — évite une longue liste Windows inutile.
    """
    physical = dedupe_printer_names(
        [n for n in names or [] if not is_virtual_printer(n)]
    )
    thermals = [n for n in physical if is_likely_thermal_printer(n)]
    return thermals if thermals else physical


def printers_for_invoice_combo(names: list[str]) -> list[str]:
    """Noms à proposer pour l'imprimante **facture** (encre / laser).

    Exclut PDF/Fax/XPS. S'il existe des imprimantes non-thermiques, on les
    propose en priorité (sinon repli sur les physiques détectées).
    """
    physical = dedupe_printer_names(
        [n for n in names or [] if not is_virtual_printer(n)]
    )
    ink = [n for n in physical if not is_likely_thermal_printer(n)]
    return ink if ink else physical


def is_likely_thermal_printer(name: str) -> bool:
    """Heuristique : nom ressemble à une imprimante ticket (POS 80C, TM-T20…)."""
    low = (name or "").strip().lower()
    if not low or is_virtual_printer(low):
        return False
    return any(hint in low for hint in _THERMAL_NAME_HINTS)


def suggest_thermal_printer(available: Optional[list[str]] = None) -> str:
    """Propose une imprimante ticket détectée (ex. POS-80C), ou chaîne vide."""
    known = available if available is not None else list_printers()
    thermals = [n for n in known if is_likely_thermal_printer(n)]
    if not thermals:
        return ""
    # Préférer un nom contenant 80 / POS.
    for preferred_token in ("pos", "80", "tm", "58"):
        for name in thermals:
            if preferred_token in name.lower():
                return name
    return thermals[0]


def match_printer_in_list(name: str, available: list[str]) -> str:
    """Retourne le nom canonique dans ``available``.

    Ordre : égalité exacte → casse → normalisation (POS 80C ≈ POS-80C) →
    containment normalisé.
    """
    name = (name or "").strip()
    if not name or not available:
        return ""
    if name in available:
        return name
    lower = name.lower()
    for candidate in available:
        if candidate.lower() == lower:
            return candidate

    key = normalize_printer_key(name)
    if not key:
        return ""
    for candidate in available:
        if normalize_printer_key(candidate) == key:
            return candidate
    # Contient : « POS 80 » trouve « POS-80C USB »
    for candidate in available:
        cand_key = normalize_printer_key(candidate)
        if key in cand_key or cand_key in key:
            # Éviter les faux positifs trop courts (ex. « 80 »).
            if len(key) >= 4 and len(cand_key) >= 4:
                return candidate
    return ""


def probe_printer_exists(name: str, timeout_s: float = 2.0) -> Optional[bool]:
    """Sonde si une file / un périphérique existe vraiment.

    Retourne :
    - ``True`` : l'imprimante (ou le chemin) est joignable ;
    - ``False`` : absente de façon certaine ;
    - ``None`` : indéterminé (outil manquant, timeout, erreur floue).

    Sur Windows, ``OpenPrinter`` est limité dans le temps pour éviter de
    rester bloqué sur une imprimante réseau fantôme.
    """
    name = (name or "").strip()
    if not name:
        return None
    if is_device_path(name):
        return Path(name).exists()

    if sys.platform.startswith("win"):  # pragma: no cover - dépend de Windows
        return _probe_windows_printer(name, timeout_s=timeout_s)

    # CUPS : lpstat -p NOM → code 0 si la file existe.
    try:
        proc = subprocess.run(
            ["lpstat", "-p", name],
            capture_output=True,
            timeout=max(1.0, float(timeout_s)),
            text=True,
            check=False,
        )
    except FileNotFoundError:
        # Sans CUPS, une file nommée n'est pas utilisable → absente.
        import shutil

        if shutil.which("lp") is None:
            return False
        return None
    except Exception:
        return None
    out = (proc.stdout or "") + (proc.stderr or "")
    low = out.lower()
    if proc.returncode == 0:
        return True
    if any(
        token in low
        for token in (
            "unknown",
            "non-existent",
            "does not exist",
            "inexistant",
            "impossible de trouver",
            "no such",
        )
    ):
        return False
    # lpstat absent de la PATH vs file inconnue : souvent returncode != 0 + message.
    if "printer" in low and ("exist" in low or "trouv" in low):
        return False
    return False if proc.returncode != 0 else True


def _probe_windows_printer(name: str, timeout_s: float = 2.0) -> Optional[bool]:
    """OpenPrinter sous timeout (évite la recherche réseau interminable)."""
    try:
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import TimeoutError as FuturesTimeout
    except Exception:
        return _probe_windows_printer_blocking(name)

    def _open() -> bool:
        import win32print

        handle = win32print.OpenPrinter(name)
        win32print.ClosePrinter(handle)
        return True

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_open)
            try:
                return bool(future.result(timeout=max(0.5, float(timeout_s))))
            except FuturesTimeout:
                logger.warning(
                    "Timeout en ouvrant l'imprimante Windows « %s » (fantôme / réseau).",
                    name,
                )
                return False
    except Exception as exc:
        # Noms typiques d'erreur : invalid printer name, introuvable…
        msg = str(exc).lower()
        if any(
            token in msg
            for token in (
                "invalid printer",
                "introuvable",
                "not found",
                "unknown printer",
                "cannot find",
                "impossible de trouver",
                "0x00000709",  # ERROR_INVALID_PRINTER_NAME
                "1801",
            )
        ):
            return False
        logger.debug("Sonde Windows indéterminée pour « %s » : %s", name, exc)
        return None


def _probe_windows_printer_blocking(name: str) -> Optional[bool]:
    try:
        import win32print

        handle = win32print.OpenPrinter(name)
        win32print.ClosePrinter(handle)
        return True
    except Exception as exc:
        msg = str(exc).lower()
        if any(
            token in msg
            for token in (
                "invalid printer",
                "introuvable",
                "not found",
                "unknown printer",
                "cannot find",
                "impossible de trouver",
                "0x00000709",
                "1801",
            )
        ):
            return False
        return None


def printer_is_available(name: str, available: Optional[list[str]] = None) -> bool:
    """Indique si l'imprimante nommée (ou le périphérique) est utilisable.

    Si la liste système est vide, on sonde le périphérique (Windows/CUPS)
    au lieu d'assumer que le nom est encore valide.
    """
    name = (name or "").strip()
    if not name:
        return True  # = imprimante par défaut du système
    if is_device_path(name):
        return Path(name).exists()
    known = available if available is not None else list_printers()
    if known:
        return bool(match_printer_in_list(name, known))
    probed = probe_printer_exists(name)
    if probed is False:
        return False
    # Indéterminé : on ne déclare pas « absent » (réglage peut encore marcher).
    return True


def resolve_printer_name(
    preferred: Optional[str] = None,
    *,
    clear_invalid: bool = True,
) -> tuple[str, str]:
    """Résout une cible d'impression, sans cibler une file fantôme.

    Retourne ``(nom_resolu, avertissement)``.
    - ``nom_resolu`` vide = imprimante par défaut du système ;
    - si la liste détectée prouve l'absence → bascule / efface ;
    - si la liste est vide → sonde (OpenPrinter / lpstat) ; absente → bascule ;
    - l'imprimante système par défaut est elle aussi vérifiée si on y bascule.
    """
    if preferred is None:
        preferred = settings_service.get_setting("printer_name", "")
    preferred = (preferred or "").strip()
    if not preferred:
        return _resolve_system_default()

    available = list_printers()

    # Chemin périphérique : seul le système de fichiers tranche.
    if is_device_path(preferred):
        if Path(preferred).exists():
            return preferred, ""
        if not clear_invalid:
            return preferred, (
                f"Périphérique « {preferred} » introuvable. "
                "Vérifiez le câble / le chemin dans Paramètres."
            )
        return _fallback_after_invalid(preferred, device=True)

    # Nom CUPS/Windows présent dans la liste (casse normalisée).
    if available:
        matched = match_printer_in_list(preferred, available)
        if matched:
            return matched, ""
        if not clear_invalid:
            return preferred, (
                f"Imprimante « {preferred} » absente de la liste détectée. "
                "Le nom est conservé ; vérifiez Paramètres → Apparence du ticket."
            )
        return _fallback_after_invalid(preferred, device=False)

    # Liste vide : ne pas faire confiance aveuglément — sonder.
    probed = probe_printer_exists(preferred)
    if probed is True:
        return preferred, ""
    if probed is None:
        # Outil de détection HS : on conserve le nom (comportement historique),
        # mais on prévient pour éviter la surprise « cherche une imprimante ».
        return preferred, (
            f"Impossible de vérifier l'imprimante « {preferred} » "
            "(détection système indisponible). "
            "Si l'impression échoue, choisissez une imprimante valide dans "
            "Paramètres → Apparence du ticket."
        )
    # probed is False
    if not clear_invalid:
        return preferred, (
            f"Imprimante « {preferred} » introuvable. "
            "Le nom est conservé ; vérifiez Paramètres → Apparence du ticket."
        )
    return _fallback_after_invalid(preferred, device=False)


def _resolve_system_default() -> tuple[str, str]:
    """Valide l'imprimante par défaut OS ; échoue clairement si fantôme."""
    system = (default_printer() or "").strip()
    if not system:
        return "", ""
    available = list_printers()
    if available and not match_printer_in_list(system, available):
        warning = (
            f"L'imprimante par défaut du système (« {system} ») est introuvable. "
            "Choisissez une imprimante valide dans Paramètres → Apparence du ticket."
        )
        logger.warning(warning)
        return "", warning
    if not available:
        probed = probe_printer_exists(system)
        if probed is False:
            warning = (
                f"L'imprimante par défaut du système (« {system} ») est introuvable. "
                "Choisissez une imprimante valide dans Paramètres → Apparence du ticket."
            )
            logger.warning(warning)
            return "", warning
    return "", ""


def _fallback_after_invalid(preferred: str, *, device: bool) -> tuple[str, str]:
    _clear_printer_setting_if_matches(preferred)
    kind = "Périphérique" if device else "Imprimante"
    base = (
        f"{kind} « {preferred} » introuvable sur ce poste. "
        "Passage sur l'imprimante par défaut du système. "
        "Choisissez une imprimante valide dans Paramètres → Apparence du ticket."
    )
    logger.warning(base)
    # Vérifier aussi le défaut système (sinon on « cherche » encore un fantôme).
    _name, extra = _resolve_system_default()
    warning = base if not extra else f"{base}\n{extra}"
    return "", warning


def _clear_printer_setting_if_matches(preferred: str) -> None:
    """Efface le réglage ticket et/ou facture s'il pointe vers le nom fantôme."""
    for key in ("printer_name", "invoice_printer_name"):
        try:
            stored = settings_service.get_setting(key, "").strip()
        except Exception:
            continue
        if stored != preferred:
            continue
        try:
            settings_service.set_setting(key, "")
        except Exception:
            logger.debug("Impossible d'effacer %s invalide.", key, exc_info=True)


# Largeur d'impression (points) selon le papier, pour redimensionner le logo.
_LOGO_WIDTH_DOTS = {"58mm": 384, "80mm": 576}


def _load_logo_image(logo_path: Optional[str], paper: str):
    """Charge et redimionne le logo pour l'impression (retourne une image PIL)."""
    if not logo_path:
        return None
    path = Path(str(logo_path))
    if not path.exists():
        return None
    try:
        from PIL import Image

        image = Image.open(path).convert("L")  # niveaux de gris
        max_width = _LOGO_WIDTH_DOTS.get(paper, 576)
        if image.width > max_width:
            ratio = max_width / float(image.width)
            image = image.resize((max_width, max(1, int(image.height * ratio))))
        return image
    except Exception:
        logger.debug("Impossible de charger le logo du ticket thermique.", exc_info=True)
        return None


def _build_escpos_serveur_bytes(
    sale,
    shop=None,
    *,
    feed_lines: int = DEFAULT_FEED_LINES,
    cut_mode: str = DEFAULT_CUT_MODE,
    logo_path: Optional[str] = None,
    paper: str = "80mm",
    design_id: Optional[str] = None,
) -> bytes:
    """ESC/POS pour designs cuisine / bon serveur (lignes stylées)."""
    _ = logo_path
    from app.printers.printer_profile import resolve_printer_profile
    from app.printers.ticket.data import TicketData
    from app.printers.ticket.registry import resolve_kitchen_design_id
    from app.printers.ticket.renderer import render_ticket
    from app.printers.ticket.styled import lines_to_escpos_bytes

    shop = shop or settings_service.get_shop_info()
    profile = resolve_printer_profile(paper=paper)
    data = TicketData.from_sale(sale, shop)
    kid = resolve_kitchen_design_id(design_id)
    styled = render_ticket(
        data,
        design_id=kid,
        role="kitchen",
        paper=paper,
        width=profile.characters_per_line,
    )
    return lines_to_escpos_bytes(
        styled,
        feed_lines=feed_lines,
        cut_mode=cut_mode,
        logo_path=None,
        paper=paper,
        include_logo=False,
        profile=profile,
    )


def _build_escpos_bytes(
    content: str,
    feed_lines: int = DEFAULT_FEED_LINES,
    cut_mode: str = DEFAULT_CUT_MODE,
    logo_path: Optional[str] = None,
    paper: str = "80mm",
    profile=None,
) -> bytes:
    """Génère le flux ESC/POS : logo + texte + avance papier + coupe.

    Encode via le profil imprimante (jamais d'UTF-8 brut vers le thermique).
    """
    from app.printers.escpos_encoder import build_escpos_document
    from app.printers.printer_profile import resolve_printer_profile

    resolved = profile or resolve_printer_profile(paper=paper)
    return build_escpos_document(
        content,
        resolved,
        feed_lines=feed_lines,
        cut_mode=cut_mode,
        logo_path=logo_path,
        paper=paper or resolved.paper_width,
        include_logo=bool(logo_path),
        styled=False,
    )


def _print_windows(raw: bytes, printer_name: str) -> PrintResult:  # pragma: no cover
    """Envoie les octets bruts à une imprimante Windows (nom ou par défaut).

    Important : on refuse d'empiler un job si l'imprimante est hors ligne /
    en pause / en erreur. Sinon Windows garde les tickets en file et les
    imprime tous d'un coup au prochain rallumage.
    """
    try:
        import win32print
    except Exception:
        return PrintResult(
            False,
            Path(),
            "Composant d'impression Windows manquant (pywin32). "
            "Réinstallez l'application ou choisissez une imprimante dans "
            "Paramètres → Apparence du ticket.",
        )

    target, hint = _pick_windows_print_target(printer_name)
    if not target:
        available = list_printers()
        tip = ""
        suggested = suggest_thermal_printer(available)
        if suggested:
            tip = (
                f" Une imprimante ticket « {suggested} » a été détectée : "
                "sélectionnez-la dans Paramètres → Apparence du ticket."
            )
        elif available:
            tip = (
                " Imprimantes vues sur ce poste : "
                + ", ".join(available[:6])
                + ("…" if len(available) > 6 else "")
                + "."
            )
        return PrintResult(
            False,
            Path(),
            "Aucune imprimante utilisable."
            + tip
            + " Vérifiez que l'imprimante (ex. POS 80C) est allumée et installée.",
        )

    preflight = _windows_printer_preflight(target)
    if preflight is not None:
        if "introuvable" in (preflight.message or "").lower() or "ouvrir" in (
            preflight.message or ""
        ).lower():
            _clear_printer_setting_if_matches(target)
            fallback = suggest_thermal_printer()
            if fallback and fallback.lower() != target.lower():
                retry = _windows_printer_preflight(fallback)
                if retry is None:
                    target = fallback
                    hint = (
                        f"Imprimante précédente indisponible — "
                        f"envoi vers « {fallback} »."
                    )
                else:
                    return PrintResult(
                        False,
                        Path(),
                        preflight.message
                        + " Astuce : dans Paramètres, choisissez l'imprimante "
                        "nommée POS 80C (ou similaire) dans la liste.",
                    )
            else:
                return PrintResult(
                    False,
                    Path(),
                    preflight.message
                    + " Astuce : dans Paramètres, choisissez l'imprimante "
                    "nommée POS 80C (ou similaire) dans la liste.",
                )
        else:
            return preflight

    job_id = 0
    written = 0
    try:
        handle = win32print.OpenPrinter(target)
        try:
            job_id = win32print.StartDocPrinter(handle, 1, ("Ticket", None, "RAW"))
            win32print.StartPagePrinter(handle)
            written = win32print.WritePrinter(handle, raw) or 0
            win32print.EndPagePrinter(handle)
            win32print.EndDocPrinter(handle)
        finally:
            win32print.ClosePrinter(handle)
    except Exception as exc:
        if job_id:
            _windows_cancel_job(target, job_id)
        msg = str(exc)
        low = msg.lower()
        if "invalid printer" in low or "0x00000709" in low or "1801" in low:
            msg = (
                f"Imprimante « {target} » introuvable. "
                "Choisissez POS 80C (ou le nom exact) dans "
                "Paramètres → Apparence du ticket."
            )
        else:
            msg = f"Échec de l'impression vers « {target} » : {exc}"
        return PrintResult(False, Path(), msg)

    if int(written) < len(raw):
        _windows_cancel_job(target, job_id)
        return PrintResult(
            False,
            Path(),
            f"Envoi incomplet vers « {target} » "
            f"({written}/{len(raw)} octets). Vérifiez le câble USB / le pilote.",
        )

    blocked = _windows_job_blocked(target, job_id, timeout_s=2.5)
    if blocked:
        _windows_cancel_job(target, job_id)
        return PrintResult(
            False,
            Path(),
            f"L'imprimante « {target} » n'a pas accepté le ticket ({blocked}). "
            "Le job a été annulé pour ne pas s'accumuler dans la file Windows. "
            "Vérifiez que l'imprimante est allumée et connectée, puis réessayez.",
        )

    message = f"Ticket envoyé à « {target} »."
    if hint:
        message = f"{hint}\n{message}"
    message += (
        " Si rien ne sort, vérifiez papier / câble "
        "(ne redémarrez pas pour « forcer »)."
    )
    return PrintResult(True, Path(), message)


def _pick_windows_print_target(printer_name: str) -> tuple[str, str]:
    """Choisit la file Windows (évite PDF virtuel si un POS ticket existe)."""
    available = list_printers()
    preferred = (printer_name or "").strip()
    if preferred:
        matched = match_printer_in_list(preferred, available) if available else preferred
        return matched or preferred, ""

    system = (default_printer() or "").strip()
    if system and not is_virtual_printer(system):
        if not available or match_printer_in_list(system, available):
            return system, ""

    suggested = suggest_thermal_printer(available)
    if suggested:
        hint = ""
        if system and is_virtual_printer(system):
            hint = (
                f"L'imprimante Windows par défaut (« {system} ») n'est pas un ticket. "
                f"Envoi vers « {suggested} »."
            )
        elif not system:
            hint = f"Aucune imprimante par défaut — envoi vers « {suggested} »."
        return suggested, hint

    return system, ""



# Drapeaux Windows indiquant qu'il ne faut PAS empiler de nouveaux jobs.
_WIN_PRINTER_BAD = (
    0x00000001  # PAUSED
    | 0x00000002  # ERROR
    | 0x00000008  # PAPER_JAM
    | 0x00000010  # PAPER_OUT
    | 0x00000040  # PAPER_PROBLEM
    | 0x00000080  # OFFLINE
    | 0x00001000  # NOT_AVAILABLE
    | 0x00100000  # USER_INTERVENTION
    | 0x00400000  # DOOR_OPEN
)

_WIN_JOB_BAD = (
    0x00000002  # ERROR
    | 0x00000020  # OFFLINE
    | 0x00000040  # PAPEROUT
    | 0x00000200  # BLOCKED_DEVQ
    | 0x00000400  # USER_INTERVENTION
)


def windows_printer_status_reason(status: int) -> str:
    """Interprète GetPrinter Status (testable hors Windows). Chaîne vide = OK."""
    status = int(status or 0)
    if not (status & _WIN_PRINTER_BAD):
        return ""
    reasons = []
    if status & 0x00000080:
        reasons.append("hors ligne")
    if status & 0x00000001:
        reasons.append("en pause")
    if status & 0x00000010:
        reasons.append("plus de papier")
    if status & 0x00000002:
        reasons.append("en erreur")
    return ", ".join(reasons) or f"état 0x{status:X}"


def windows_job_status_reason(status: int) -> str:
    """Interprète EnumJobs Status. Chaîne vide = pas de blocage détecté."""
    status = int(status or 0)
    if not (status & _WIN_JOB_BAD):
        return ""
    if status & 0x00000020:
        return "hors ligne"
    if status & 0x00000040:
        return "plus de papier"
    if status & 0x00000002:
        return "erreur"
    return "bloqué"


def _windows_printer_preflight(printer_name: str) -> Optional[PrintResult]:
    """Refuse l'impression si l'imprimante Windows est clairement indisponible."""
    exists = probe_printer_exists(printer_name, timeout_s=2.0)
    if exists is False:
        return PrintResult(
            False,
            Path(),
            f"Imprimante « {printer_name} » introuvable sur ce poste. "
            "Aucun ticket n'a été mis en file d'attente. "
            "Choisissez une imprimante valide dans Paramètres → Apparence du ticket.",
        )

    try:
        import win32print

        handle = win32print.OpenPrinter(printer_name)
        try:
            info = win32print.GetPrinter(handle, 2)
        finally:
            win32print.ClosePrinter(handle)
    except Exception as exc:
        return PrintResult(
            False,
            Path(),
            f"Impossible d'ouvrir « {printer_name} » : {exc}",
        )

    reason = windows_printer_status_reason(int(info.get("Status", 0) or 0))
    if reason:
        return PrintResult(
            False,
            Path(),
            f"Imprimante « {printer_name} » indisponible ({reason}). "
            "Allumez-la / reconnectez le USB avant de réimprimer. "
            "Aucun ticket n'a été mis en file d'attente.",
        )
    return None


def _windows_job_blocked(printer_name: str, job_id: int, timeout_s: float = 2.5) -> str:
    """Retourne un motif si le job est bloqué ; chaîne vide sinon."""
    if not job_id:
        return ""
    import time

    try:
        import win32print
    except Exception:
        return ""

    deadline = time.monotonic() + max(0.5, float(timeout_s))
    while time.monotonic() < deadline:
        try:
            handle = win32print.OpenPrinter(printer_name)
            try:
                jobs = win32print.EnumJobs(handle, 0, -1, 1)
            finally:
                win32print.ClosePrinter(handle)
        except Exception:
            return ""
        match = next((j for j in jobs if int(j.get("JobId", 0)) == int(job_id)), None)
        if match is None:
            # Job disparu de la file → traité (imprimé ou consommé).
            return ""
        reason = windows_job_status_reason(int(match.get("Status", 0) or 0))
        if reason:
            return reason
        # Encore en cours : on laisse une chance courte, puis on considère OK.
        time.sleep(0.25)
    return ""


def _windows_cancel_job(printer_name: str, job_id: int) -> None:
    if not job_id:
        return
    try:
        import win32print

        handle = win32print.OpenPrinter(printer_name)
        try:
            win32print.SetJob(handle, int(job_id), 0, None, win32print.JOB_CONTROL_DELETE)
        finally:
            win32print.ClosePrinter(handle)
    except Exception:
        logger.debug("Annulation du job d'impression impossible.", exc_info=True)


def purge_printer_queue(printer_name: Optional[str] = None) -> PrintResult:
    """Vide la file d'attente Windows de l'imprimante (évite la rafale au reboot)."""
    if not sys.platform.startswith("win"):  # pragma: no cover
        return PrintResult(
            False, Path(), "La purge de file n'est disponible que sous Windows."
        )
    try:
        import win32print
    except Exception as exc:
        return PrintResult(False, Path(), f"Module d'impression Windows absent : {exc}")

    name, warning = resolve_printer_name(
        printer_name if printer_name is not None else None
    )
    target = name or default_printer()
    if not target:
        msg = "Aucune imprimante à purger."
        if warning:
            msg = f"{warning}\n{msg}"
        return PrintResult(False, Path(), msg)
    if (
        warning
        and "L'imprimante par défaut du système" in warning
        and "introuvable" in warning
    ):
        return PrintResult(False, Path(), warning)
    preflight = _windows_printer_preflight(target)
    if preflight is not None:
        return preflight
    try:
        handle = win32print.OpenPrinter(target)
        try:
            jobs = win32print.EnumJobs(handle, 0, -1, 1)
            cancelled = 0
            for job in jobs:
                job_id = int(job.get("JobId", 0) or 0)
                if not job_id:
                    continue
                try:
                    win32print.SetJob(
                        handle, job_id, 0, None, win32print.JOB_CONTROL_DELETE
                    )
                    cancelled += 1
                except Exception:
                    logger.debug("Job %s non annulé.", job_id, exc_info=True)
        finally:
            win32print.ClosePrinter(handle)
    except Exception as exc:
        return PrintResult(False, Path(), f"Impossible de purger « {target} » : {exc}")
    message = f"File d'attente de « {target} » vidée ({cancelled} job(s) annulé(s))."
    if warning:
        message = f"{warning}\n{message}"
    return PrintResult(
        True,
        Path(),
        message,
    )


def _print_posix(raw: bytes, printer_name: str) -> PrintResult:
    """Impression sous Linux/macOS : périphérique brut ou CUPS (lp)."""
    # 1) Chemin de périphérique explicite (ex. /dev/usb/lp0).
    if printer_name and ("/" in printer_name or printer_name.startswith("\\")):
        try:
            with open(printer_name, "wb") as device:
                device.write(raw)
                device.flush()
            return PrintResult(True, Path(), f"Imprimé sur « {printer_name} ».")
        except OSError as exc:
            return PrintResult(False, Path(), f"Accès imprimante impossible : {exc}")

    # 2) Sinon, on tente CUPS via la commande « lp » (impression brute).
    command = ["lp", "-o", "raw"]
    if printer_name:
        command += ["-d", printer_name]
    try:
        proc = subprocess.run(
            command, input=raw, capture_output=True, timeout=20, check=False
        )
    except FileNotFoundError:
        return PrintResult(
            False, Path(), "Aucune imprimante configurée (CUPS/lp introuvable)."
        )
    except Exception as exc:  # pragma: no cover - dépend du système
        return PrintResult(False, Path(), f"Échec de l'impression : {exc}")
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip() or "erreur inconnue"
        return PrintResult(False, Path(), f"Échec de l'impression : {detail}")
    where = printer_name or "imprimante par défaut"
    return PrintResult(True, Path(), f"Imprimé sur « {where} ».")


def print_ticket(
    sale,
    shop=None,
    paper: str = "80mm",
    printer_name: Optional[str] = None,
    *,
    design_id: Optional[str] = None,
    role: str = "client",
) -> PrintResult:
    """Imprime réellement le ticket / la facture et retourne le résultat.

    - Format thermique (58/80 mm) : copie texte + envoi ESC/POS RAW.
    - Format ``demi-A4`` : PDF 210×148,5 mm + impression bureau (non RAW).
    - ``role="kitchen"`` : design bon serveur / cuisine (sans prix).
    """
    from app.printers.half_a4_invoice import is_half_a4, print_half_a4_invoice
    from app.printers.ticket.registry import get_design, resolve_design_id

    from app.printers.printer_targets import (
        get_invoice_printer_name,
        get_thermal_printer_name,
    )

    shop = shop or settings_service.get_shop_info()
    if is_half_a4(paper) and role == "client":
        # Archive texte + impression PDF facture (imprimante encre si configurée).
        text_path = save_ticket_file(sale, shop, paper)
        target = (
            printer_name
            if printer_name is not None
            else get_invoice_printer_name()
        )
        result = print_half_a4_invoice(sale, shop=shop, printer_name=target)
        if result.file_path and result.file_path.suffix.lower() == ".pdf":
            if text_path and text_path.exists():
                result.message = (
                    f"{result.message}\nCopie texte : {text_path}"
                ).strip()
        elif not result.file_path:
            result.file_path = text_path
        return result

    path = save_ticket_file(sale, shop, paper, design_id=design_id, role=role)
    resolved = resolve_design_id(design_id, role=role)
    design = get_design(resolved)
    from app.printers.ticket.options import load_ticket_options

    opts = load_ticket_options()
    from app.printers.shop_logos import resolve_logo_path

    logo_for_print = ""
    if design.uses_logo and opts.show_logo:
        logo_for_print = resolve_logo_path(
            logo_path=str(getattr(shop, "logo_path", "") or ""),
            shop_type=str(getattr(shop, "shop_type", "") or ""),
        )
    target = (
        printer_name if printer_name is not None else get_thermal_printer_name()
    )
    if design.category == "kitchen":
        result = _send_content(
            "",
            target,
            logo_path=None,
            paper=paper,
            sale=sale,
            layout=resolved,
            design_id=resolved,
            role="kitchen",
        )
    else:
        content = render_ticket_text(
            sale, shop, paper, design_id=resolved, role="client"
        )
        result = _send_content(
            content,
            target,
            logo_path=logo_for_print or None,
            paper=paper,
            sale=sale,
            design_id=resolved,
            role="client",
        )
    result.file_path = path
    return result


def print_design_test(
    design_id: str,
    *,
    paper: Optional[str] = None,
    printer_name: Optional[str] = None,
) -> PrintResult:
    """Imprime un ticket de test avec le design choisi (données fictives)."""
    from types import SimpleNamespace

    from app.printers.ticket.data import sample_ticket_data
    from app.printers.ticket.registry import get_design

    paper = paper or settings_service.get_setting("ticket_format", "80mm")
    if paper not in ("58mm", "80mm"):
        paper = "80mm"
    data = sample_ticket_data()
    design = get_design(design_id)
    # Transforme TicketData en objet sale-like pour print_ticket.
    sale = SimpleNamespace(
        ticket_number=data.ticket_number,
        date=data.moment,
        cashier_name=data.cashier_name,
        client_id=None,
        client_name="",
        items=[
            SimpleNamespace(
                product_name=it.name,
                quantity=it.quantity,
                unit_price=it.unit_price,
                line_total=it.line_total,
            )
            for it in data.items
        ],
        subtotal=data.subtotal,
        discount=data.discount,
        total=data.total,
        amount_received=data.amount_received,
        change_due=data.change_due,
        payments=[
            SimpleNamespace(method=p.method, amount=p.amount) for p in data.payments
        ],
    )
    shop = SimpleNamespace(
        name=data.shop_name,
        address=data.shop_address,
        phone=data.shop_phone,
        currency=data.currency,
        logo_path="",
        ticket_footer=data.footer,
    )
    role = "kitchen" if design.category == "kitchen" else "client"
    return print_ticket(
        sale,
        shop=shop,
        paper=paper,
        printer_name=printer_name,
        design_id=design.id,
        role=role,
    )


def _send_content(
    content: str,
    printer_name: Optional[str] = None,
    logo_path: Optional[str] = None,
    paper: str = "80mm",
    sale=None,
    layout: Optional[str] = None,
    design_id: Optional[str] = None,
    role: str = "client",
) -> PrintResult:
    """Envoie un contenu déjà formaté à l'imprimante selon les réglages courants."""
    from app.printers.printer_profile import resolve_printer_profile
    from app.printers.ticket.data import TicketData
    from app.printers.ticket.registry import get_design, resolve_design_id
    from app.printers.ticket.renderer import render_ticket
    from app.printers.ticket.styled import lines_to_escpos_bytes

    printer_name = (
        printer_name
        if printer_name is not None
        else settings_service.get_setting("printer_name", "")
    ).strip()
    printer_name, printer_warning = resolve_printer_name(printer_name)

    # Défaut système fantôme : ne pas lancer une recherche Windows/CUPS inutile.
    if (
        not printer_name
        and printer_warning
        and "L'imprimante par défaut du système" in printer_warning
        and "introuvable" in printer_warning
    ):
        return PrintResult(False, Path(), printer_warning)

    try:
        feed_lines = int(
            settings_service.get_setting("ticket_feed_lines", str(DEFAULT_FEED_LINES))
        )
    except (TypeError, ValueError):
        feed_lines = DEFAULT_FEED_LINES
    cut_mode = settings_service.get_setting("ticket_cut_mode", DEFAULT_CUT_MODE)
    if cut_mode not in ("full", "partial", "none"):
        cut_mode = DEFAULT_CUT_MODE

    resolved = resolve_design_id(design_id or layout, role=role)
    design = get_design(resolved)
    if design.preferred_feed is not None:
        feed_lines = min(feed_lines, design.preferred_feed)

    profile = resolve_printer_profile(paper=paper)

    if sale is not None:
        data = TicketData.from_sale(sale)
        styled = render_ticket(
            data,
            design_id=resolved,
            role=role,
            paper=paper,
            width=profile.characters_per_line,
        )
        raw = lines_to_escpos_bytes(
            styled,
            feed_lines=feed_lines,
            cut_mode=cut_mode,
            logo_path=logo_path if design.uses_logo else None,
            paper=paper,
            include_logo=bool(design.uses_logo and logo_path),
            profile=profile,
        )
    else:
        raw = _build_escpos_bytes(
            content,
            feed_lines=feed_lines,
            cut_mode=cut_mode,
            logo_path=logo_path,
            paper=paper,
            profile=profile,
        )

    if sys.platform.startswith("win"):
        result = _print_windows(raw, printer_name)
    else:
        result = _print_posix(raw, printer_name)

    if printer_warning:
        result.message = (
            f"{printer_warning}\n{result.message}".strip()
            if result.message
            else printer_warning
        )

    if not result.printed and not result.message:
        result.message = (
            "Aucune imprimante configurée. "
            "Paramètres → Apparence du ticket → Imprimante."
        )
    return result


def print_test_page(printer_name: Optional[str] = None) -> PrintResult:
    """Imprime une page de test (pour régler avance papier / coupe par modèle)."""
    from app.printers.printer_profile import resolve_printer_profile
    from app.printers.shop_logos import resolve_logo_path

    shop = settings_service.get_shop_info()
    profile = resolve_printer_profile()
    paper = profile.paper_width
    width = profile.characters_per_line
    logo = resolve_logo_path(
        logo_path=str(getattr(shop, "logo_path", "") or ""),
        shop_type=str(getattr(shop, "shop_type", "") or ""),
    )

    lines = [
        _center(shop.name or "Gestion Commerciale", width),
        _line("=", width),
        _center("PAGE DE TEST", width),
        _center(f"Format {paper} — {width} car.", width),
        _center(f"{profile.escpos_codepage} / {profile.encoding}", width),
        _line("-", width),
        "Si vous lisez ces lignes entièrement",
        "et que le papier est coupé,",
        "l'imprimante est bien configuree.",
        _line("-", width),
        _center(datetime.now().strftime("%d/%m/%Y %H:%M"), width),
    ]
    return _send_content(
        "\n".join(lines), printer_name, logo_path=logo or None, paper=paper
    )


def print_encoding_test_page(printer_name: Optional[str] = None) -> PrintResult:
    """Page de test des accents français (avant une vraie facture).

    Permet de vérifier que le codepage du profil est correct : si les accents
    sortent en chinois / symboles, changer le profil dans Apparence du ticket.
    """
    from app.printers.escpos_encoder import ACCENT_TEST_SAMPLE
    from app.printers.printer_profile import resolve_printer_profile

    shop = settings_service.get_shop_info()
    profile = resolve_printer_profile()
    paper = profile.paper_width
    width = profile.characters_per_line
    sep = _line("-", width)
    lines = [
        _center(shop.name or "Gestion Commerciale", width),
        _line("=", width),
        _center("TEST ACCENTS FR", width),
        _center(profile.label[:width], width),
        f"Codepage: {profile.escpos_codepage}",
        f"Codec: {profile.encoding}  |  {paper} / {width}c",
        sep,
        ACCENT_TEST_SAMPLE.rstrip("\n"),
        sep,
        "Si accents OK → profil correct.",
        "Si chinois / symboles → changer profil.",
        sep,
        _center(datetime.now().strftime("%d/%m/%Y %H:%M"), width),
    ]
    return _send_content(
        "\n".join(lines), printer_name, logo_path=None, paper=paper
    )


def render_debt_payment_text(
    *,
    client_name: str,
    amount: float,
    payment_method: str,
    remaining_after: float,
    note: str = "",
    cashier: str = "",
    payment_id: Optional[int] = None,
    shop=None,
    paper: str = "80mm",
) -> str:
    """Construit le reçu texte d'un règlement de dette client."""
    shop = shop or settings_service.get_shop_info()
    # Force thermique pour les reçus dette (pas de demi-A4 ici).
    if paper not in ("58mm", "80mm"):
        paper = "80mm"
    width = WIDTH_CHARS.get(paper, 48)
    currency = shop.currency or "FCFA"
    lines = [
        _center(shop.name or "Commerce", width),
        _line("=", width),
        _center("RECU REGLEMENT DETTE", width),
        _line("-", width),
        _row("Date", datetime.now().strftime("%d/%m/%Y %H:%M"), width),
    ]
    if payment_id:
        lines.append(_row("N°", str(payment_id), width))
    if cashier:
        lines.append(_row("Caissier", cashier[: width // 2], width))
    lines.append(_row("Client", (client_name or "—")[: width // 2], width))
    lines.append(_line("-", width))
    lines.append(_row("Montant payé", format_money(amount, currency), width))
    lines.append(_row("Mode", payment_method or "Espèces", width))
    lines.append(_row("Reste dû", format_money(remaining_after, currency), width))
    if note:
        lines.append(_line("-", width))
        lines.append(f"Note : {note[: width * 2]}")
    lines.append(_line("=", width))
    lines.append(_center("Merci", width))
    lines.append("")
    return "\n".join(lines)


def save_debt_payment_file(
    content: str, payment_id: Optional[int] = None
) -> Path:
    """Archive le reçu de règlement dans le dossier tickets."""
    config.ensure_directories()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"dette_paye_{payment_id or 'x'}_{stamp}"
    path = config.TICKET_DIR / f"{base}.txt"
    counter = 1
    while path.exists():
        path = config.TICKET_DIR / f"{base}_{counter}.txt"
        counter += 1
    path.write_text(content, encoding="utf-8")
    return path


def print_debt_payment(
    *,
    client_name: str,
    amount: float,
    payment_method: str,
    remaining_after: float,
    note: str = "",
    cashier: str = "",
    payment_id: Optional[int] = None,
    printer_name: Optional[str] = None,
) -> PrintResult:
    """Imprime (et archive) un reçu de règlement de dette."""
    shop = settings_service.get_shop_info()
    paper = settings_service.get_setting("ticket_format", "80mm")
    if paper not in ("58mm", "80mm"):
        paper = "80mm"
    content = render_debt_payment_text(
        client_name=client_name,
        amount=amount,
        payment_method=payment_method,
        remaining_after=remaining_after,
        note=note,
        cashier=cashier,
        payment_id=payment_id,
        shop=shop,
        paper=paper,
    )
    path = save_debt_payment_file(content, payment_id=payment_id)
    printer = printer_name or settings_service.get_setting("printer_name", "")
    result = _send_content(
        content, printer or None, logo_path=shop.logo_path, paper=paper
    )
    result.file_path = path
    if not result.printed:
        result.message = (
            f"{result.message}\nCopie : {path}".strip()
            if result.message
            else f"Reçu enregistré : {path}"
        )
    return result

