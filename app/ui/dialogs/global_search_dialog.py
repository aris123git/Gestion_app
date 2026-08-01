"""Recherche universelle (clients, produits, factures, dettes, fournisseurs)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
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
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._search)
        self.query.textChanged.connect(lambda _text="": self._search_timer.start())
        self.query.returnPressed.connect(self._accept_current)
        layout.addWidget(self.query)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._accept_item)
        self.list.itemActivated.connect(self._accept_item)
        layout.addWidget(self.list)

        self.hint = QLabel("Saisissez au moins 2 caractères.")
        self.hint.setStyleSheet("color:#64748b;")
        layout.addWidget(self.hint)

        row = QHBoxLayout()
        open_btn = QPushButton("Ouvrir")
        open_btn.setObjectName("Primary")
        open_btn.clicked.connect(self._accept_current)
        close = QPushButton("Fermer")
        close.clicked.connect(self.reject)
        row.addStretch()
        row.addWidget(open_btn)
        row.addWidget(close)
        layout.addLayout(row)
        self.query.setFocus()

    def _search(self) -> None:
        self.list.clear()
        text = self.query.text()
        hits = SearchService.search(text)
        if len(text.strip()) < 2:
            self.hint.setText("Saisissez au moins 2 caractères.")
        else:
            self.hint.setText(f"{len(hits)} résultat(s)" if hits else "Aucun résultat.")
        for hit in hits:
            item = QListWidgetItem(f"[{hit.kind}] {hit.title} — {hit.subtitle}")
            item.setData(Qt.ItemDataRole.UserRole, hit)
            self.list.addItem(item)

    def _accept_current(self) -> None:
        if self.list.count() == 0 and self.query.text().strip():
            self._search()
        item = self.list.currentItem()
        if item is None and self.list.count() > 0:
            item = self.list.item(0)
        if item is not None:
            self._accept_item(item)

    def _accept_item(self, item: QListWidgetItem) -> None:
        self.selected_hit = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
