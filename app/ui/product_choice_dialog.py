"""Premier démarrage NexaGes : choix Gestion App ou Maquis Caisse."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.services import product_profile
from app.ui.widgets.helpers import activate_and_center


class ProductChoiceDialog(QDialog):
    """Écran affiché une seule fois sur un nouvel ordinateur."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{product_profile.PARENT_NAME} — Choix du produit")
        self.setMinimumSize(720, 420)
        self.selected: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        brand = QLabel(product_profile.PARENT_NAME)
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setStyleSheet("font-size: 28px; font-weight: 800; color: #0f172a;")
        root.addWidget(brand)

        vendor = QLabel(f"Logiciel de gestion — {product_profile.PARENT_VENDOR}")
        vendor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vendor.setStyleSheet("color: #64748b; font-size: 13px;")
        root.addWidget(vendor)

        intro = QLabel(
            "Nouvel ordinateur détecté. Choisissez le produit à utiliser sur ce poste. "
            "Ce choix est enregistré et ne sera plus demandé."
        )
        intro.setWordWrap(True)
        intro.setAlignment(Qt.AlignmentFlag.AlignCenter)
        intro.setStyleSheet("color: #334155; font-size: 14px; margin: 8px 0 12px 0;")
        root.addWidget(intro)

        cards = QHBoxLayout()
        cards.setSpacing(16)
        cards.addWidget(
            self._build_card(
                product_profile.PRODUCT_GESTION,
                product_profile.PRODUCT_LABELS[product_profile.PRODUCT_GESTION],
                product_profile.PRODUCT_DESCRIPTIONS[product_profile.PRODUCT_GESTION],
            )
        )
        cards.addWidget(
            self._build_card(
                product_profile.PRODUCT_MAQUIS,
                product_profile.PRODUCT_LABELS[product_profile.PRODUCT_MAQUIS],
                product_profile.PRODUCT_DESCRIPTIONS[product_profile.PRODUCT_MAQUIS],
            )
        )
        root.addLayout(cards, 1)

        hint = QLabel(
            "Ensuite : saisie de la clé d'activation, puis configuration du commerce."
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #94a3b8; font-size: 12px;")
        root.addWidget(hint)

        activate_and_center(self)

    def _build_card(self, code: str, title: str, description: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("ProductCard")
        frame.setStyleSheet(
            "#ProductCard {"
            " border: 1px solid #cbd5e1; border-radius: 12px; background: #ffffff;"
            "}"
            "#ProductCard:hover { border: 2px solid #2563eb; }"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        label = QLabel(title)
        label.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(label)

        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #64748b; font-size: 13px;")
        layout.addWidget(desc, 1)

        btn = QPushButton(f"Choisir {title}")
        btn.setObjectName("Primary")
        btn.setMinimumHeight(40)
        btn.clicked.connect(lambda: self._choose(code))
        layout.addWidget(btn)
        return frame

    def _choose(self, code: str) -> None:
        product_profile.set_product(code)
        self.selected = code
        self.accept()
