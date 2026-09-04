"""Encodage ESC/POS sûr pour imprimantes thermiques (accents FR).

Ne jamais envoyer d'UTF-8 brut à l'imprimante : on fixe un codepage
(ESC t) puis on encode avec le codec Python correspondant.
Les glyphes impossibles sont translittérés (é→e en dernier recours).
"""

from __future__ import annotations

import logging
import unicodedata
from typing import Optional

from app.printers.printer_profile import PrinterProfile

logger = logging.getLogger(__name__)

# Remplacements avant encodage (glyphes absents des codepages DOS courants).
_CHAR_MAP = {
    "œ": "oe",
    "Œ": "OE",
    "æ": "ae",
    "Æ": "AE",
    "€": "E",
    "×": "x",
    "·": ".",
    "—": "-",
    "–": "-",
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    "°": "o",
    "«": '"',
    "»": '"',
    # Coins arrondis → coins droits (présents en CP850/CP437).
    "╭": "┌",
    "╮": "┐",
    "╰": "└",
    "╯": "┘",
}


def prepare_text(text: str, profile: PrinterProfile) -> str:
    """Normalise le texte pour le codepage cible (sans perdre les accents utiles)."""
    if not text:
        return ""
    out: list[str] = []
    for ch in text:
        if ch in _CHAR_MAP:
            out.append(_CHAR_MAP[ch] if profile.transliterate else ch)
        else:
            out.append(ch)
    return "".join(out)


def _strip_accents(text: str) -> str:
    """Dernier recours : é → e (NFD + suppression des diacritiques)."""
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def encode_text(text: str, profile: PrinterProfile) -> bytes:
    """Encode ``text`` pour l'imprimante — jamais d'UTF-8 brut."""
    prepared = prepare_text(text, profile)
    encoding = profile.encoding or "cp850"
    try:
        return prepared.encode(encoding)
    except UnicodeEncodeError:
        pass

    # Deuxième essai : translittération des restes impossibles caractère par caractère.
    buf = bytearray()
    for ch in prepared:
        try:
            buf.extend(ch.encode(encoding))
        except UnicodeEncodeError:
            if not profile.transliterate:
                buf.extend(b"?")
                continue
            plain = _strip_accents(ch)
            try:
                buf.extend(plain.encode(encoding))
            except UnicodeEncodeError:
                # ASCII strict.
                try:
                    buf.extend(plain.encode("ascii", errors="replace"))
                except Exception:
                    buf.extend(b"?")
    return bytes(buf)


def configure_escpos_printer(dummy, profile: PrinterProfile) -> None:
    """Fixe le codepage ESC/POS sur l'instance python-escpos."""
    code = profile.escpos_codepage or "CP850"
    try:
        dummy.charcode(code)
    except Exception:
        logger.debug(
            "charcode(%s) refusé — tentative CP850.", code, exc_info=True
        )
        try:
            dummy.charcode("CP850")
        except Exception:
            logger.debug("Impossible de fixer le codepage ESC/POS.", exc_info=True)


def write_text(dummy, text: str, profile: PrinterProfile) -> None:
    """Écrit du texte via le buffer brut, avec encodage profil (pas MagicEncode UTF-8).

    On contourne ``dummy.text()`` (MagicEncode AUTO) qui peut changer de
    codepage en cours de route et produire des glyphes asiatiques.
    """
    if not text:
        return
    # S'assurer que le codepage est actif avant les octets.
    configure_escpos_printer(dummy, profile)
    data = encode_text(text, profile)
    # python-escpos : _raw ajoute au buffer.
    try:
        dummy._raw(data)
    except Exception:
        # Repli : text() après charcode forcé.
        logger.debug("Écriture _raw impossible, repli text().", exc_info=True)
        try:
            dummy.charcode(profile.escpos_codepage)
        except Exception:
            pass
        dummy.text(prepare_text(text, profile))


def build_escpos_document(
    lines_or_content,
    profile: PrinterProfile,
    *,
    feed_lines: int = 5,
    cut_mode: str = "full",
    logo_path: Optional[str] = None,
    paper: str = "80mm",
    include_logo: bool = True,
    styled: bool = False,
) -> bytes:
    """Construit un document ESC/POS complet à partir de texte ou de StyledLine."""
    from app.printers.ticket.styled import StyledLine

    feed_lines = max(0, int(feed_lines))
    cut_map = {"full": "FULL", "partial": "PART"}
    try:
        from escpos.printer import Dummy

        dummy = Dummy()
        configure_escpos_printer(dummy, profile)

        if include_logo and logo_path:
            try:
                from app.printers.thermal_printer import _load_logo_image

                logo = _load_logo_image(logo_path, paper)
                if logo is not None:
                    dummy.set(align="center")
                    dummy.image(logo)
                    if profile.supports_center:
                        dummy.set(align="left")
            except Exception:
                logger.debug("Logo ignoré.", exc_info=True)

        if styled:
            for line in lines_or_content:
                assert isinstance(line, StyledLine)
                align = line.align if profile.supports_center else "left"
                if align not in ("left", "center", "right"):
                    align = "left"
                bold = bool(line.bold and profile.supports_bold)
                w = 2 if line.double_width else 1
                h = 2 if line.double_height else 1
                dummy.set(align=align, bold=bold, width=w, height=h)
                text = line.text or ""
                if not text.endswith("\n"):
                    text = text + "\n"
                write_text(dummy, text, profile)
            dummy.set(align="left", bold=False, width=1, height=1)
        else:
            content = str(lines_or_content or "")
            if not content.endswith("\n"):
                content += "\n"
            write_text(dummy, content, profile)

        if feed_lines:
            write_text(dummy, "\n" * feed_lines, profile)
        if cut_mode != "none" and profile.supports_cut:
            mode = cut_map.get(cut_mode, "FULL")
            try:
                dummy.cut(mode=mode)
            except Exception:
                try:
                    dummy.cut()
                except Exception:
                    pass
        return dummy.output
    except Exception:
        logger.exception("Génération ESC/POS échouée — repli octets encodés.")
        if styled:
            from app.printers.ticket.styled import lines_to_text

            text = lines_to_text(lines_or_content, profile.characters_per_line)
        else:
            text = str(lines_or_content or "")
        data = encode_text(text + ("\n" * feed_lines), profile)
        if cut_mode != "none":
            data += b"\x1d\x56\x00"
        return data


# Phrase de test des accents français.
ACCENT_TEST_SAMPLE = (
    "Test accents FR\n"
    "é è ê ë à â ä ù û ü î ï ô ö ç\n"
    "É È À Ç Œ œ\n"
    "Café, école, français, hôtel\n"
    "Crème brûlée — 1 000 FCFA\n"
)
