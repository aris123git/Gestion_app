"""Moteur de layout : observe le viewport et publie un LayoutProfile."""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from PySide6.QtCore import QObject, Signal

from app.ui.responsive.viewport import LayoutProfile, compute_profile

logger = logging.getLogger(__name__)


def decision_key(profile: LayoutProfile) -> Tuple:
    """Clé de décision (ignore les pixels bruts pour éviter le churn au resize).

    Le content_width est regroupé par pas de 80 px : assez fin pour les
    largeurs de colonnes, assez large pour ne pas republier à chaque frame
    d'une animation showMaximized sous Windows.
    """
    return (
        profile.width_mode,
        profile.height_mode,
        profile.sidebar_mode,
        profile.density,
        profile.card_columns,
        profile.stack_panels,
        profile.content_width // 80,
    )


class LayoutEngine(QObject):
    """
    Équivalent Qt du « Viewport Manager + Layout Engine ».

    Toute l'UI s'abonne à `changed` (ou à `AppState.layout_changed`) au lieu
    de disperser des seuils @media dans chaque page.
    """

    changed = Signal(object)  # LayoutProfile

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._profile: Optional[LayoutProfile] = None
        self._decision_key: Optional[Tuple] = None

    @property
    def profile(self) -> Optional[LayoutProfile]:
        return self._profile

    def update(self, width: int, height: int) -> LayoutProfile:
        profile = compute_profile(width, height)
        key = decision_key(profile)
        # Toujours mémoriser les dimensions courantes, mais n'émettre que si
        # les décisions de layout changent (évite le gel au maximize Windows).
        if self._decision_key == key:
            self._profile = profile
            return profile
        self._profile = profile
        self._decision_key = key
        logger.debug(
            "Layout %sx%s → width=%s height=%s sidebar=%s density=%s cards=%s",
            profile.width,
            profile.height,
            profile.width_mode,
            profile.height_mode,
            profile.sidebar_mode,
            profile.density,
            profile.card_columns,
        )
        self.changed.emit(profile)
        return profile

    def force_emit(self) -> None:
        if self._profile is not None:
            self.changed.emit(self._profile)
