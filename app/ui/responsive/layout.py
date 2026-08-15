"""Moteur de layout : observe le viewport et publie un LayoutProfile."""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, Signal

from app.ui.responsive.viewport import LayoutProfile, compute_profile

logger = logging.getLogger(__name__)


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

    @property
    def profile(self) -> Optional[LayoutProfile]:
        return self._profile

    def update(self, width: int, height: int) -> LayoutProfile:
        profile = compute_profile(width, height)
        if self._profile == profile:
            return profile
        self._profile = profile
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
