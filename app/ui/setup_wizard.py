"""Assistant de premier démarrage : saisie des informations du commerce."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app import config
from app.services import settings_service
from app.ui.widgets.helpers import activate_and_center

SHOP_TYPES = [
    "Boutique",
    "Poissonnerie",
    "Pharmacie",
    "Quincaillerie",
    "Boucherie",
    "Boulangerie",
    "Supérette",
    "Magasin d'électronique",
    "Autre commerce",
]

CURRENCIES = ["FCFA", "EUR", "USD", "MAD", "DZD", "TND", "GNF", "XOF", "XAF"]


class SetupWizard(QDialog):
    """Recueille les informations de base du commerce au tout premier lancement."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bienvenue - Configuration du commerce")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._logo_path = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        title = QLabel("Configuration initiale")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Renseignez les informations de votre commerce. "
            "Elles seront modifiables à tout moment dans les paramètres."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #64748b;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(10)

        self.name = QLineEdit()
        self.name.setPlaceholderText("Nom du commerce")
        self.address = QLineEdit()
        self.phone = QLineEdit()
        self.currency = QComboBox()
        self.currency.addItems(CURRENCIES)
        self.currency.setEditable(True)
        self.shop_type = QComboBox()
        self.shop_type.addItems(SHOP_TYPES)

        logo_row = QHBoxLayout()
        self.logo_label = QLabel("Aucun logo sélectionné")
        self.logo_label.setStyleSheet("color: #94a3b8;")
        logo_button = QPushButton("Choisir un logo…")
        logo_button.clicked.connect(self._pick_logo)
        logo_row.addWidget(self.logo_label, 1)
        logo_row.addWidget(logo_button)

        form.addRow("Nom du commerce *", self.name)
        form.addRow("Adresse", self.address)
        form.addRow("Téléphone", self.phone)
        form.addRow("Devise", self.currency)
        form.addRow("Type de commerce", self.shop_type)
        form.addRow("Logo", logo_row)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch()
        save = QPushButton("Enregistrer et démarrer")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def showEvent(self, event) -> None:  # noqa: N802 - signature Qt
        super().showEvent(event)
        activate_and_center(self)

    def _pick_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir un logo", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self._logo_path = path
            self.logo_label.setText(Path(path).name)
            self.logo_label.setStyleSheet("color: #16a34a;")

    def _save(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(
                self, "Configuration", "Le nom du commerce est obligatoire."
            )
            return

        logo_stored = ""
        if self._logo_path:
            config.ensure_directories()
            dest = config.LOGO_DIR / f"logo{Path(self._logo_path).suffix}"
            try:
                shutil.copy2(self._logo_path, dest)
                logo_stored = str(dest)
            except OSError:
                logo_stored = self._logo_path

        settings_service.save_shop_info(
            name=self.name.text().strip(),
            address=self.address.text().strip(),
            phone=self.phone.text().strip(),
            currency=self.currency.currentText().strip() or "FCFA",
            shop_type=self.shop_type.currentText(),
            logo_path=logo_stored,
            is_configured=True,
        )
        self.accept()
