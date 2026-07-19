"""Fenêtre d'activation affichée au premier démarrage."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.services import activation_service
from app.ui.widgets.helpers import activate_and_center


class ActivationDialog(QDialog):
    """Demande le code d'activation ; enregistre l'activation si correct."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Activation requise")
        self.setModal(True)
        self.setFixedWidth(460)
        self.activated = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 30, 30, 30)
        outer.setSpacing(14)

        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Activation requise")
        title.setObjectName("PageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        message = QLabel(
            "Ce logiciel doit être activé sur cet ordinateur.\n"
            "Entrez le code d'activation fourni par votre installateur."
        )
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setStyleSheet("color: #64748b;")

        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Code d'activation")
        self.code_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_input.returnPressed.connect(self._activate)

        self.activate_button = QPushButton("Activer")
        self.activate_button.setObjectName("Primary")
        self.activate_button.clicked.connect(self._activate)

        quit_button = QPushButton("Quitter")
        quit_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(quit_button)
        buttons.addStretch()
        buttons.addWidget(self.activate_button)

        layout.addWidget(title)
        layout.addWidget(message)
        layout.addSpacing(6)
        layout.addWidget(QLabel("Entrez le code d'activation :"))
        layout.addWidget(self.code_input)
        layout.addLayout(buttons)
        outer.addWidget(card)

    def showEvent(self, event) -> None:  # noqa: N802 - signature Qt
        super().showEvent(event)
        activate_and_center(self)
        self.code_input.setFocus()

    def _activate(self) -> None:
        code = self.code_input.text().strip()
        if not code:
            QMessageBox.warning(self, "Activation", "Veuillez saisir un code.")
            return
        if activation_service.activate(code):
            self.activated = True
            QMessageBox.information(
                self, "Activation", "Logiciel activé avec succès. Merci !"
            )
            self.accept()
        else:
            QMessageBox.critical(
                self, "Activation", "Code d'activation invalide. Veuillez réessayer."
            )
            self.code_input.clear()
            self.code_input.setFocus()
