"""Petits graphiques dessinés directement (courbe d'évolution, mini-courbe de carte)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


def short_amount(v: float) -> str:
    v = float(v)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}".rstrip("0").rstrip(".") + " M"
    if abs(v) >= 1000:
        return f"{v / 1000:.0f} k"
    return f"{v:.0f}"


class Sparkline(QWidget):
    def __init__(self, color: str = "#2563eb", parent=None) -> None:
        super().__init__(parent)
        self.color = QColor(color)
        self.values: list[float] = []
        self.setFixedSize(76, 34)

    def set_values(self, values: list[float]) -> None:
        self.values = list(values)
        self.update()

    def paintEvent(self, _e) -> None:
        if len(self.values) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        lo, hi = min(self.values), max(self.values)
        span = (hi - lo) or 1.0
        w, h, n = self.width() - 4, self.height() - 6, len(self.values)
        pts = [QPointF(2 + i * w / (n - 1), 3 + h - (v - lo) / span * h) for i, v in enumerate(self.values)]
        path = QPainterPath(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        pen = QPen(self.color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPath(path)


class LineChart(QWidget):
    """Courbe avec aire douce, axes et étiquettes."""

    def __init__(self, color: str = "#2563eb", parent=None) -> None:
        super().__init__(parent)
        self.color = QColor(color)
        self.labels: list[str] = []
        self.values: list[float] = []
        self.empty_text = "Aucune vente sur la période."
        self.setMinimumHeight(190)

    def set_data(self, labels: list[str], values: list[float]) -> None:
        self.labels, self.values = list(labels), list(values)
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPointSize(8)
        p.setFont(font)
        grey = QColor("#94a3b8")
        if not self.values or max(self.values) <= 0:
            p.setPen(grey)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)
            return
        left, right, top, bottom = 44, 10, 8, 22
        area = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)
        hi = max(self.values)
        step = 10 ** (len(str(int(hi))) - 1)
        for m in (1, 2, 2.5, 5, 10):
            if hi <= m * step:
                hi = m * step
                break
        for i in range(5):
            y = area.bottom() - area.height() * i / 4
            p.setPen(QPen(QColor("#eef1f5"), 1))
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            p.setPen(grey)
            p.drawText(QRectF(0, y - 8, left - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, short_amount(hi * i / 4))
        n = len(self.values)
        xs = [area.left() + (area.width() * i / (n - 1) if n > 1 else area.width() / 2) for i in range(n)]
        ys = [area.bottom() - v / hi * area.height() for v in self.values]
        line = QPainterPath(QPointF(xs[0], ys[0]))
        for x, y in zip(xs[1:], ys[1:]):
            line.lineTo(x, y)
        fill = QPainterPath(line)
        fill.lineTo(xs[-1], area.bottom())
        fill.lineTo(xs[0], area.bottom())
        fill.closeSubpath()
        soft = QColor(self.color)
        soft.setAlpha(32)
        p.fillPath(fill, soft)
        p.setPen(QPen(self.color, 2.4))
        p.drawPath(line)
        if n <= 40:
            p.setBrush(self.color)
            for x, y in zip(xs, ys):
                p.drawEllipse(QPointF(x, y), 2.6, 2.6)
        p.setPen(grey)
        ticks = min(n, 6)
        for k in range(ticks):
            i = round(k * (n - 1) / (ticks - 1)) if ticks > 1 else 0
            p.drawText(QRectF(min(max(xs[i] - 30, 0), self.width() - 60), area.bottom() + 4, 60, 16), Qt.AlignmentFlag.AlignCenter, self.labels[i])


class MultiLineChart(QWidget):
    """Courbes superposées (ex. CA et bénéfice), sans aire remplie, avec axes et étiquettes."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.labels: list[str] = []
        self.series: list[tuple[str, QColor, list[float]]] = []
        self.empty_text = "Aucune donnée sur la période."
        self.setMinimumHeight(170)

    def set_series(self, labels: list[str], series: list[tuple[str, str, list[float]]]) -> None:
        """series : liste de (nom, couleur, valeurs) — toutes de la même longueur que labels."""
        self.labels = list(labels)
        self.series = [(name, QColor(color), list(values)) for name, color, values in series]
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPointSize(8)
        p.setFont(font)
        grey = QColor("#94a3b8")
        all_values = [v for _n, _c, vals in self.series for v in vals]
        if not self.labels or not all_values or max(all_values) <= 0:
            p.setPen(grey)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)
            return
        left, right, top, bottom = 48, 10, 8, 22
        area = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)
        hi = max(all_values)
        step = 10 ** (len(str(int(hi))) - 1)
        for m in (1, 2, 2.5, 5, 10):
            if hi <= m * step:
                hi = m * step
                break
        for i in range(5):
            y = area.bottom() - area.height() * i / 4
            p.setPen(QPen(QColor("#eef1f5"), 1))
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            p.setPen(grey)
            p.drawText(QRectF(0, y - 8, left - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, short_amount(hi * i / 4))
        n = len(self.labels)
        xs = [area.left() + (area.width() * i / (n - 1) if n > 1 else area.width() / 2) for i in range(n)]
        for _name, color, values in self.series:
            ys = [area.bottom() - v / hi * area.height() for v in values]
            line = QPainterPath(QPointF(xs[0], ys[0]))
            for x, y in zip(xs[1:], ys[1:]):
                line.lineTo(x, y)
            p.setPen(QPen(color, 2.4))
            p.drawPath(line)
        p.setPen(grey)
        ticks = min(n, 6)
        for k in range(ticks):
            i = round(k * (n - 1) / (ticks - 1)) if ticks > 1 else 0
            p.drawText(QRectF(min(max(xs[i] - 30, 0), self.width() - 60), area.bottom() + 4, 60, 16), Qt.AlignmentFlag.AlignCenter, self.labels[i])
