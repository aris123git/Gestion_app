"""Relève de caisse — Maquis Caisse PC."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.i18n import t
from app.ui.dialogs.cash_session_dialog import close_cash_session_flow, ensure_cash_session_open


class CaisseSessionPage(QWidget):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        title = QLabel(t("Relève de caisse"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        layout.addWidget(
            QLabel(
                t(
                    "Ouvrez la caisse au début de service et faites la relève (fermeture) en fin de journée."
                )
            )
        )
        open_btn = QPushButton(t("Ouvrir la caisse"))
        open_btn.setObjectName("Primary")
        open_btn.clicked.connect(self._open)
        close_btn = QPushButton(t("Fermer la caisse"))
        close_btn.clicked.connect(self._close)
        layout.addWidget(open_btn)
        layout.addWidget(close_btn)
        layout.addStretch()

    def _open(self) -> None:
        ensure_cash_session_open(self, self.state)

    def _close(self) -> None:
        close_cash_session_flow(self, self.state)

    def refresh(self) -> None:
        pass
