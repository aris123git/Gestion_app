"""Calcul du profil d'affichage à partir de la largeur et de la hauteur."""

from __future__ import annotations

from dataclasses import dataclass

from app.ui.responsive import breakpoints as bp


@dataclass(frozen=True)
class LayoutProfile:
    """Snapshot immuable de l'espace disponible et des décisions de layout."""

    width: int
    height: int
    width_mode: str  # mobile | compact | desktop | large
    height_mode: str  # very_short | short | normal | tall
    sidebar_mode: str  # full | icons | drawer
    density: str  # comfortable | cozy | compact
    card_columns: int
    content_width: int

    @property
    def is_narrow(self) -> bool:
        return self.width_mode in {"mobile", "compact"}

    @property
    def is_short(self) -> bool:
        return self.height_mode in {"very_short", "short"}

    @property
    def stack_panels(self) -> bool:
        """True si les panneaux côte-à-côte doivent s'empiler (ex. caisse)."""
        if self.width_mode == "mobile":
            return True
        # Laptop / compact : empiler dès que la zone utile est trop étroite.
        return self.content_width < bp.STACK_PANELS_CONTENT_WIDTH


def width_mode_for(width: int) -> str:
    if width < bp.WIDTH_MOBILE:
        return "mobile"
    if width < bp.WIDTH_COMPACT:
        return "compact"
    if width < bp.WIDTH_DESKTOP:
        return "desktop"
    return "large"


def height_mode_for(height: int) -> str:
    if height < bp.HEIGHT_VERY_SHORT:
        return "very_short"
    if height < bp.HEIGHT_SHORT:
        return "short"
    if height >= bp.HEIGHT_TALL:
        return "tall"
    return "normal"


def sidebar_mode_for(width_mode: str) -> str:
    if width_mode == "mobile":
        return bp.SIDEBAR_DRAWER
    if width_mode == "compact":
        return bp.SIDEBAR_ICONS
    return bp.SIDEBAR_FULL


def density_for(width_mode: str, height_mode: str) -> str:
    if height_mode == "very_short" or width_mode == "mobile":
        return bp.DENSITY_COMPACT
    if height_mode == "short" or width_mode == "compact":
        return bp.DENSITY_COZY
    return bp.DENSITY_COMFORTABLE


def card_columns_for(width_mode: str, content_width: int) -> int:
    if width_mode == "mobile" or content_width < 560:
        return 1
    if width_mode == "compact" or content_width < 900:
        return 2
    if width_mode == "desktop" or content_width < 1200:
        return 3
    return 4


def sidebar_width_for(sidebar_mode: str) -> int:
    if sidebar_mode == bp.SIDEBAR_ICONS:
        return bp.SIDEBAR_WIDTH_ICONS
    if sidebar_mode == bp.SIDEBAR_DRAWER:
        return 0
    return bp.SIDEBAR_WIDTH_FULL


def compute_profile(width: int, height: int) -> LayoutProfile:
    """Point d'entrée unique : largeur + hauteur → décisions de layout."""
    width = max(0, int(width))
    height = max(0, int(height))
    w_mode = width_mode_for(width)
    h_mode = height_mode_for(height)
    s_mode = sidebar_mode_for(w_mode)
    density = density_for(w_mode, h_mode)
    side_w = sidebar_width_for(s_mode)
    # En mode drawer la barre top ~48px ; sinon toute la largeur hors sidebar.
    top_reserve = 48 if s_mode == bp.SIDEBAR_DRAWER else 0
    content_width = max(0, width - side_w)
    content_height = max(0, height - top_reserve)
    _ = content_height  # réservé pour extensions (densité verticale pages)
    return LayoutProfile(
        width=width,
        height=height,
        width_mode=w_mode,
        height_mode=h_mode,
        sidebar_mode=s_mode,
        density=density,
        card_columns=card_columns_for(w_mode, content_width),
        content_width=content_width,
    )
