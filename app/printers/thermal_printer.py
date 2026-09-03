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


def list_printers() -> list[str]:
    """Retourne la liste des imprimantes installées sur le poste.

    - Windows : via ``win32print`` (imprimantes locales et partagées) ;
    - Linux/macOS : via ``lpstat`` (CUPS).
    En cas d'échec ou d'absence d'outil, retourne une liste vide.
    """
    if sys.platform.startswith("win"):  # pragma: no cover - dépend de Windows
        try:
            import win32print

            flags = (
                win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            )
            return [printer[2] for printer in win32print.EnumPrinters(flags)]
        except Exception:
            return []
    try:
        proc = subprocess.run(
            ["lpstat", "-a"], capture_output=True, timeout=5, text=True, check=False
        )
        return [
            line.split()[0]
            for line in proc.stdout.splitlines()
            if line.strip()
        ]
    except Exception:
        return []


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


def printer_is_available(name: str, available: Optional[list[str]] = None) -> bool:
    """Indique si l'imprimante nommée (ou le périphérique) est utilisable.

    Si la détection système renvoie une liste vide, on considère le nom
    comme encore utilisable (évite de casser un réglage qui fonctionnait
    quand ``lpstat`` / l'énumération Windows échoue temporairement).
    """
    name = (name or "").strip()
    if not name:
        return True  # = imprimante par défaut du système
    if is_device_path(name):
        return Path(name).exists()
    known = available if available is not None else list_printers()
    if not known:
        # Liste indisponible ≠ imprimante absente : on conserve le réglage.
        return True
    return name in known


def resolve_printer_name(
    preferred: Optional[str] = None,
    *,
    clear_invalid: bool = True,
) -> tuple[str, str]:
    """Résout une cible d'impression, sans casser un réglage encore valide.

    Retourne ``(nom_resolu, avertissement)``.
    - ``nom_resolu`` vide = imprimante par défaut du système ;
    - on ne bascule / n'efface que si la liste détectée est non vide et
      que le nom n'y figure pas (ou chemin périphérique inexistant).
    """
    if preferred is None:
        preferred = settings_service.get_setting("printer_name", "")
    preferred = (preferred or "").strip()
    if not preferred:
        return "", ""

    available = list_printers()

    # Chemin périphérique : seul le système de fichiers tranche.
    if is_device_path(preferred):
        if Path(preferred).exists():
            return preferred, ""
        # Chemin mort : on garde le nom si clear_invalid=False, sinon défaut.
        if not clear_invalid:
            return preferred, (
                f"Périphérique « {preferred} » introuvable. "
                "Vérifiez le câble / le chemin dans Paramètres."
            )
        _clear_printer_setting_if_matches(preferred)
        warning = (
            f"Périphérique « {preferred} » introuvable. "
            "Passage sur l'imprimante par défaut du système."
        )
        logger.warning(warning)
        return "", warning

    # Nom CUPS/Windows : ne juger que si on a réellement une liste.
    if not available:
        return preferred, ""
    if preferred in available:
        return preferred, ""

    if not clear_invalid:
        return preferred, (
            f"Imprimante « {preferred} » absente de la liste détectée. "
            "Le nom est conservé ; vérifiez Paramètres → Apparence & Ticket."
        )

    _clear_printer_setting_if_matches(preferred)
    warning = (
        f"Imprimante « {preferred} » introuvable sur ce poste. "
        "Passage sur l'imprimante par défaut du système. "
        "Choisissez une imprimante valide dans Paramètres → Apparence & Ticket."
    )
    logger.warning(warning)
    return "", warning


def _clear_printer_setting_if_matches(preferred: str) -> None:
    stored = settings_service.get_setting("printer_name", "").strip()
    if stored != preferred:
        return
    try:
        settings_service.set_setting("printer_name", "")
    except Exception:
        logger.debug("Impossible d'effacer printer_name invalide.", exc_info=True)


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
    from app.printers.ticket.data import TicketData
    from app.printers.ticket.registry import resolve_kitchen_design_id
    from app.printers.ticket.renderer import render_ticket
    from app.printers.ticket.styled import lines_to_escpos_bytes

    shop = shop or settings_service.get_shop_info()
    data = TicketData.from_sale(sale, shop)
    kid = resolve_kitchen_design_id(design_id)
    styled = render_ticket(data, design_id=kid, role="kitchen", paper=paper)
    return lines_to_escpos_bytes(
        styled,
        feed_lines=feed_lines,
        cut_mode=cut_mode,
        logo_path=None,
        paper=paper,
        include_logo=False,
    )


def _build_escpos_bytes(
    content: str,
    feed_lines: int = DEFAULT_FEED_LINES,
    cut_mode: str = DEFAULT_CUT_MODE,
    logo_path: Optional[str] = None,
    paper: str = "80mm",
) -> bytes:
    """Génère le flux ESC/POS : logo + texte + avance papier + coupe.

    - ``logo_path`` : image du logo à imprimer en tête (facultatif) ;
    - ``feed_lines`` : lignes vides ajoutées après le contenu pour faire sortir
      entièrement le ticket au-delà du massicot / de la barre de découpe ;
    - ``cut_mode`` : ``"full"``, ``"partial"`` ou ``"none"``.
    """
    feed_lines = max(0, int(feed_lines))
    try:
        from escpos.printer import Dummy

        dummy = Dummy()
        # Logo centré en haut du ticket (best-effort : ignoré si non imprimable).
        logo = _load_logo_image(logo_path, paper)
        if logo is not None:
            try:
                dummy.set(align="center")
                dummy.image(logo)
                dummy.set(align="left")
            except Exception:
                logger.debug(
                    "Logo thermique ignoré par le générateur ESC/POS.",
                    exc_info=True,
                )
        dummy.text(content)
        if feed_lines:
            dummy.text("\n" * feed_lines)
        if cut_mode != "none":
            escpos_mode = _CUT_MODES.get(cut_mode, "FULL")
            try:
                dummy.cut(mode=escpos_mode)
            except Exception:
                try:
                    dummy.cut()
                except Exception:
                    logger.debug("Commande de coupe ESC/POS ignorée.", exc_info=True)
        return dummy.output
    except Exception:
        data = content.encode("utf-8", errors="replace")
        data += b"\n" * feed_lines
        if cut_mode != "none":
            data += b"\x1d\x56\x00"  # GS V 0 : coupe complète
        return data


def _print_windows(raw: bytes, printer_name: str) -> PrintResult:  # pragma: no cover
    """Envoie les octets bruts à une imprimante Windows (nom ou par défaut).

    Important : on refuse d'empiler un job si l'imprimante est hors ligne /
    en pause / en erreur. Sinon Windows garde les tickets en file et les
    imprime tous d'un coup au prochain rallumage.
    """
    try:
        import win32print
    except Exception as exc:
        return PrintResult(False, Path(), f"Module d'impression Windows absent : {exc}")

    target = printer_name or win32print.GetDefaultPrinter()
    if not target:
        return PrintResult(
            False,
            Path(),
            "Aucune imprimante Windows configurée. "
            "Installez une imprimante ou choisissez-en une dans "
            "Paramètres → Apparence & Ticket.",
        )

    # Pré-contrôle : ne pas alimenter la file si le périphérique est indisponible.
    preflight = _windows_printer_preflight(target)
    if preflight is not None:
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
        return PrintResult(False, Path(), f"Échec de l'impression Windows : {exc}")

    if int(written) < len(raw):
        _windows_cancel_job(target, job_id)
        return PrintResult(
            False,
            Path(),
            f"Envoi incomplet vers « {target} » "
            f"({written}/{len(raw)} octets). Vérifiez le câble USB / le pilote.",
        )

    # Court contrôle post-envoi : si le job reste bloqué (offline / erreur),
    # on l'annule pour éviter l'impression en rafale au redémarrage.
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

    return PrintResult(
        True,
        Path(),
        f"Ticket envoyé à « {target} ». "
        "Si rien ne sort, vérifiez papier / câble (ne redémarrez pas pour « forcer »).",
    )


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
    target = name or win32print.GetDefaultPrinter()
    if not target:
        msg = "Aucune imprimante à purger."
        if warning:
            msg = f"{warning}\n{msg}"
        return PrintResult(False, Path(), msg)
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

    shop = shop or settings_service.get_shop_info()
    if is_half_a4(paper) and role == "client":
        # Archive texte + impression PDF facture.
        text_path = save_ticket_file(sale, shop, paper)
        result = print_half_a4_invoice(sale, shop=shop, printer_name=printer_name)
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
    use_logo = bool(design.uses_logo and opts.show_logo and shop.logo_path)
    if design.category == "kitchen":
        result = _send_content(
            "",
            printer_name,
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
            printer_name,
            logo_path=shop.logo_path if use_logo else None,
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

    if sale is not None:
        data = TicketData.from_sale(sale)
        styled = render_ticket(
            data, design_id=resolved, role=role, paper=paper
        )
        raw = lines_to_escpos_bytes(
            styled,
            feed_lines=feed_lines,
            cut_mode=cut_mode,
            logo_path=logo_path if design.uses_logo else None,
            paper=paper,
            include_logo=bool(design.uses_logo and logo_path),
        )
    else:
        raw = _build_escpos_bytes(
            content,
            feed_lines=feed_lines,
            cut_mode=cut_mode,
            logo_path=logo_path,
            paper=paper,
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
            "Paramètres → Apparence & Ticket → Imprimante."
        )
    return result


def print_test_page(printer_name: Optional[str] = None) -> PrintResult:
    """Imprime une page de test (pour régler avance papier / coupe par modèle)."""
    shop = settings_service.get_shop_info()
    paper = settings_service.get_setting("ticket_format", "80mm")
    width = WIDTH_CHARS.get(paper, 48)

    lines = [
        _center(shop.name or "Gestion Commerciale", width),
        _line("=", width),
        _center("PAGE DE TEST", width),
        _center(f"Format {paper}", width),
        _line("-", width),
        "Si vous lisez ces lignes entièrement",
        "et que le papier est coupé,",
        "l'imprimante est bien configurée.",
        _line("-", width),
        _center(datetime.now().strftime("%d/%m/%Y %H:%M"), width),
    ]
    return _send_content(
        "\n".join(lines), printer_name, logo_path=shop.logo_path, paper=paper
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

