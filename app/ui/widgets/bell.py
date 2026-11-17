"""Cloche d'alertes animée : elle grossit, se balance, puis revient (toutes les minutes s'il y a des alertes)."""

from __future__ import annotations

import math

from PySide6.QtCore import QByteArray, QEasingCurve, QObject, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/>'
        '<path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>')
CANVAS = 30            # place pour le grossissement
ICON = 22              # taille de la cloche au repos


def bell_icon(color: str, scale: float = 1.0, angle: float = 0.0) -> QIcon:
    ratio = 2
    pm = QPixmap(CANVAS * ratio, CANVAS * ratio)
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(CANVAS / 2, CANVAS * 0.2)          # pivot en haut de la cloche
    painter.rotate(angle)
    painter.scale(scale, scale)
    side = ICON
    renderer = QSvgRenderer(QByteArray(_SVG.format(c=color).encode()))
    renderer.render(painter, __import__("PySide6.QtCore", fromlist=["QRectF"]).QRectF(-side / 2, -CANVAS * 0.2 + (CANVAS - side) / 2, side, side))
    painter.end()
    return QIcon(pm)


class BellAnimator(QObject):
    """Pilote l'icône de plusieurs boutons (menu et barre du haut)."""

    def __init__(self, buttons, parent=None, period_ms: int = 60_000):
        super().__init__(parent)
        self.buttons = list(buttons)
        self.active = False
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(1500)
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._anim.valueChanged.connect(lambda v: self._paint(float(v)))
        self._anim.finished.connect(lambda: self._paint(0.0))
        self._timer = QTimer(self)
        self._timer.setInterval(period_ms)
        self._timer.timeout.connect(self.ring)
        self._timer.start()
        for b in self.buttons:
            b.setIconSize(QSize(CANVAS, CANVAS))
        self._paint(0.0)

    def set_active(self, active: bool) -> None:
        changed = active != self.active
        self.active = active
        self._paint(0.0)
        if active and changed:
            self.ring()

    def ring(self) -> None:
        if self.active and self._anim.state() != QVariantAnimation.State.Running:
            self._anim.start()

    def _paint(self, t: float) -> None:
        env = math.sin(math.pi * t)                       # 0 -> 1 -> 0 : grossit puis revient
        scale = 1.0 + 0.35 * env
        angle = 16 * env * math.sin(t * math.pi * 8)      # balancement
        color = "#fca5a5" if self.active else "#cbd5e1"
        icon = bell_icon(color, scale, angle)
        for b in self.buttons:
            b.setIcon(icon)
