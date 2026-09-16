"""Mouvements de stock — onglet historique (équivalent Routes.MOUVEMENTS)."""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.ui.pages.stock_page import StockPage


class StockMovementsPage(QWidget):
    """Réutilise StockPage en affichant directement l'historique."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._stock = StockPage(state)
        layout.addWidget(self._stock)
        self._stock.tabs.setCurrentIndex(1)

    def refresh(self) -> None:
        self._stock.refresh()
