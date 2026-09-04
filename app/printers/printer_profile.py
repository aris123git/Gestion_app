"""Profils d'imprimantes thermiques (largeur, codepage, capacités).

Le contenu du ticket reste indépendant de l'imprimante : seul le profil
adapte la largeur (caractères/ligne) et l'encodage ESC/POS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.services import settings_service

# Largeurs connues (caractères / ligne Font A typique).
CPL_58 = 32
CPL_80 = 48
CPL_80_NARROW = 42  # certains modèles 80 mm en police large


@dataclass(frozen=True)
class PrinterProfile:
    """Configuration d'une imprimante thermique pour ESC/POS."""

    id: str
    label: str
    paper_width: str  # "58mm" | "80mm"
    characters_per_line: int
    # Codec Python (cp850, cp437, cp1252, …).
    encoding: str
    # Nom passé à Dummy.charcode() (CP850, CP437, CP1252, …).
    escpos_codepage: str
    supports_bold: bool = True
    supports_center: bool = True
    supports_cut: bool = True
    supports_qr: bool = False
    # Remplacer les glyphes impossibles (œ, coins arrondis, …).
    transliterate: bool = True

    @property
    def is_58mm(self) -> bool:
        return self.paper_width == "58mm"


# Profils prêts à l'emploi (l'utilisateur choisit selon le modèle réel).
PRINTER_PROFILES: dict[str, PrinterProfile] = {
    "generic_80_cp850": PrinterProfile(
        id="generic_80_cp850",
        label="Générique 80 mm — CP850 (recommandé FR)",
        paper_width="80mm",
        characters_per_line=CPL_80,
        encoding="cp850",
        escpos_codepage="CP850",
    ),
    "generic_58_cp850": PrinterProfile(
        id="generic_58_cp850",
        label="Générique 58 mm — CP850 (recommandé FR)",
        paper_width="58mm",
        characters_per_line=CPL_58,
        encoding="cp850",
        escpos_codepage="CP850",
    ),
    "generic_80_cp858": PrinterProfile(
        id="generic_80_cp858",
        label="Générique 80 mm — CP858",
        paper_width="80mm",
        characters_per_line=CPL_80,
        encoding="cp858",
        escpos_codepage="CP858",
    ),
    "generic_58_cp858": PrinterProfile(
        id="generic_58_cp858",
        label="Générique 58 mm — CP858",
        paper_width="58mm",
        characters_per_line=CPL_58,
        encoding="cp858",
        escpos_codepage="CP858",
    ),
    "generic_80_cp437": PrinterProfile(
        id="generic_80_cp437",
        label="Générique 80 mm — CP437 (compat. ancienne)",
        paper_width="80mm",
        characters_per_line=CPL_80,
        encoding="cp437",
        escpos_codepage="CP437",
    ),
    "generic_58_cp437": PrinterProfile(
        id="generic_58_cp437",
        label="Générique 58 mm — CP437 (compat. ancienne)",
        paper_width="58mm",
        characters_per_line=CPL_58,
        encoding="cp437",
        escpos_codepage="CP437",
    ),
    "generic_80_cp1252": PrinterProfile(
        id="generic_80_cp1252",
        label="Générique 80 mm — Windows-1252",
        paper_width="80mm",
        characters_per_line=CPL_80,
        encoding="cp1252",
        escpos_codepage="CP1252",
    ),
    "generic_58_cp1252": PrinterProfile(
        id="generic_58_cp1252",
        label="Générique 58 mm — Windows-1252",
        paper_width="58mm",
        characters_per_line=CPL_58,
        encoding="cp1252",
        escpos_codepage="CP1252",
    ),
    "generic_80_narrow_cp850": PrinterProfile(
        id="generic_80_narrow_cp850",
        label="80 mm police large — 42 car. — CP850",
        paper_width="80mm",
        characters_per_line=CPL_80_NARROW,
        encoding="cp850",
        escpos_codepage="CP850",
    ),
}

DEFAULT_PROFILE_ID_80 = "generic_80_cp850"
DEFAULT_PROFILE_ID_58 = "generic_58_cp850"

SETTING_PRINTER_PROFILE = "printer_profile_id"


def get_profile(profile_id: Optional[str] = None) -> PrinterProfile:
    """Retourne un profil par id (fallback générique 80 mm CP850)."""
    if profile_id and profile_id in PRINTER_PROFILES:
        return PRINTER_PROFILES[profile_id]
    return PRINTER_PROFILES[DEFAULT_PROFILE_ID_80]


def list_profiles() -> list[PrinterProfile]:
    return list(PRINTER_PROFILES.values())


def resolve_printer_profile(
    *,
    paper: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> PrinterProfile:
    """Résout le profil actif depuis les paramètres + format papier.

    - Si un profil est choisi explicitement, on l'utilise.
    - Sinon on dérive 58/80 mm + CP850 (bon défaut français).
    - Le format papier des paramètres peut surcharger la largeur du profil
      si l'utilisateur a changé ticket_format sans changer de profil.
    """
    pid = profile_id or settings_service.get_setting(SETTING_PRINTER_PROFILE, "")
    paper = paper or settings_service.get_setting("ticket_format", "80mm")
    if paper not in ("58mm", "80mm"):
        # demi-A4 / autre : profil 80 pour la copie thermique éventuelle.
        paper = "80mm"

    if pid and pid in PRINTER_PROFILES:
        profile = PRINTER_PROFILES[pid]
        # Harmoniser CPL si le format papier des paramètres diffère.
        if profile.paper_width != paper:
            cpl = CPL_58 if paper == "58mm" else profile.characters_per_line
            if paper == "80mm" and profile.characters_per_line <= CPL_58:
                cpl = CPL_80
            return PrinterProfile(
                id=profile.id,
                label=profile.label,
                paper_width=paper,
                characters_per_line=cpl if paper == "58mm" else (
                    profile.characters_per_line if profile.characters_per_line >= 40 else CPL_80
                ),
                encoding=profile.encoding,
                escpos_codepage=profile.escpos_codepage,
                supports_bold=profile.supports_bold,
                supports_center=profile.supports_center,
                supports_cut=profile.supports_cut,
                supports_qr=profile.supports_qr,
                transliterate=profile.transliterate,
            )
        return profile

    # Aucun profil stocké : défaut selon le papier.
    return get_profile(
        DEFAULT_PROFILE_ID_58 if paper == "58mm" else DEFAULT_PROFILE_ID_80
    )


def save_printer_profile_id(profile_id: str) -> None:
    if profile_id not in PRINTER_PROFILES:
        profile_id = DEFAULT_PROFILE_ID_80
    settings_service.set_setting(SETTING_PRINTER_PROFILE, profile_id)
    # Aligner ticket_format sur la largeur du profil (sans forcer demi-A4).
    profile = PRINTER_PROFILES[profile_id]
    current = settings_service.get_setting("ticket_format", "80mm")
    if current in ("58mm", "80mm") and current != profile.paper_width:
        settings_service.set_setting("ticket_format", profile.paper_width)
