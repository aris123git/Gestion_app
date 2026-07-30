"""Recherche universelle (clients, produits, factures, dettes, fournisseurs)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from app.services.search_service import SearchService


class GlobalSearchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recherche universelle")
        self.setModal(True)
        self.resize(560, 420)
        self.selected_hit = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        self.query = QLineEdit()
        self.query.setPlaceholderText(
            "Client, téléphone, produit, facture, dette, fournisseur…"
        )
        self.query.textChanged.connect(self._search)
        layout.addWidget(self.query)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._accept_item)
        layout.addWidget(self.list)

        self.hint = QLabel("Saisissez au moins 2 caractères.")
        self.hint.setStyleSheet("color:#64748b;")
        layout.addWidget(self.hint)

        row = QHBoxLayout()
        close = QPushButton("Fermer")
        close.clicked.connect(self.reject)
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        self.query.setFocus()

    def _search(self, text: str) -> None:
        self.list.clear()
        hits = SearchService.search(text)
        self.hint.setText(f"{len(hits)} résultat(s)" if hits else "Aucun résultat.")
        for hit in hits:
            item = QListWidgetItem(f"[{hit.kind}] {hit.title} — {hit.subtitle}")
            item.setData(Qt.ItemDataRole.UserRole, hit)
            self.list.addItem(item)

    def _accept_item(self, item: QListWidgetItem) -> None:
        self.selected_hit = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
