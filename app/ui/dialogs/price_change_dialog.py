"""Dialogue proposé lorsqu'un prix est modifié dans le panier."""
from __future__ import annotations
from app.i18n import t
from PySide6.QtWidgets import QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QRadioButton, QVBoxLayout

class PriceChangeDialog(QDialog):
    """Demande si la modification de prix est ponctuelle ou définitive.

    Résultat accessible via ``self.choice`` :

    - ``"once"``      : modifier uniquement cette vente ;
    - ``"permanent"`` : mettre à jour définitivement le prix du produit.
    """

    def __init__(self, product_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t('Modification du prix'))
        self.setModal(True)
        self.setMinimumWidth(440)
        self.choice = 'once'
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header_banner = QFrame()
        header_banner.setObjectName('DialogHeaderBanner')
        header_layout = QVBoxLayout(header_banner)
        header_layout.setContentsMargins(20, 14, 20, 16)
        header_layout.setSpacing(2)
        question = QLabel(t('Que souhaitez-vous faire ?'))
        question.setStyleSheet('font-size: 16px; font-weight: 800;')
        header_layout.addWidget(question)
        detail = QLabel(f'Produit : {product_name}')
        detail.setStyleSheet('font-size: 12px;')
        header_layout.addWidget(detail)
        outer.addWidget(header_banner)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(10)
        outer.addLayout(layout, 1)

        self.option_once = QRadioButton(t('Modifier uniquement cette vente'))
        self.option_perm = QRadioButton(t('Mettre à jour définitivement le prix du produit'))
        self.option_once.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.option_once)
        group.addButton(self.option_perm)
        for radio in (self.option_once, self.option_perm):
            card = QFrame()
            card.setObjectName('SmallCard')
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.addWidget(radio)
            layout.addWidget(card)

        layout.addSpacing(4)
        buttons = QHBoxLayout()
        cancel = QPushButton(t('Annuler'))
        cancel.clicked.connect(self.reject)
        confirm = QPushButton(t('Valider'))
        confirm.setObjectName('Primary')
        confirm.clicked.connect(self._confirm)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(confirm)
        layout.addLayout(buttons)

    def _confirm(self) -> None:
        self.choice = 'permanent' if self.option_perm.isChecked() else 'once'
        self.accept()
