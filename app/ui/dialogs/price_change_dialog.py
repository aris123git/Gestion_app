"""Dialogue proposé lorsqu'un prix est modifié dans le panier."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)


class PriceChangeDialog(QDialog):
    """Demande si la modification de prix est ponctuelle ou définitive.

    Résultat accessible via ``self.choice`` :

    - ``"once"``      : modifier uniquement cette vente ;
    - ``"permanent"`` : mettre à jour définitivement le prix du produit.
    """

    def __init__(self, product_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modification du prix")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.choice = "once"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        question = QLabel("Que souhaitez-vous faire ?")
        question.setObjectName("SectionTitle")
        detail = QLabel(f"Produit : {product_name}")
        detail.setStyleSheet("color: #64748b;")

        self.option_once = QRadioButton("Modifier uniquement cette vente")
        self.option_perm = QRadioButton(
            "Mettre à jour définitivement le prix du produit"
        )
        self.option_once.setChecked(True)

        group = QButtonGroup(self)
        group.addButton(self.option_once)
        group.addButton(self.option_perm)

        confirm = QPushButton("Valider")
        confirm.setObjectName("Primary")
        confirm.clicked.connect(self._confirm)

        layout.addWidget(question)
        layout.addWidget(detail)
        layout.addSpacing(6)
        layout.addWidget(self.option_once)
        layout.addWidget(self.option_perm)
        layout.addSpacing(6)
        layout.addWidget(confirm)

    def _confirm(self) -> None:
        self.choice = "permanent" if self.option_perm.isChecked() else "once"
        self.accept()
