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
    """Choix Gestion App / Maquis Caisse (1er démarrage ou bascule démo)."""

    def __init__(self, parent=None, *, switch_mode: bool = False):
        super().__init__(parent)
        self.setWindowTitle(f"{product_profile.PARENT_NAME} — Choix du produit")
        self.setMinimumSize(720, 420)
        self.selected: str | None = None
        self.switch_mode = switch_mode
        current = product_profile.get_product() if switch_mode else None

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

        if switch_mode:
            intro_text = (
                "Choisissez le produit à présenter sur ce poste. "
                "Après confirmation, l'application devra être relancée."
            )
            if current:
                intro_text += f" Produit actuel : <b>{product_profile.product_label(current)}</b>."
        else:
            intro_text = (
                "Nouvel ordinateur détecté. Choisissez le produit à utiliser sur ce poste. "
                "Ce choix est enregistré et ne sera plus demandé."
            )
        intro = QLabel(intro_text)
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
                current=current,
            )
        )
        cards.addWidget(
            self._build_card(
                product_profile.PRODUCT_MAQUIS,
                product_profile.PRODUCT_LABELS[product_profile.PRODUCT_MAQUIS],
                product_profile.PRODUCT_DESCRIPTIONS[product_profile.PRODUCT_MAQUIS],
                current=current,
            )
        )
        root.addLayout(cards, 1)

        if switch_mode:
            hint_text = "Réservé à la démonstration. Relancez l'application après le changement."
        else:
            hint_text = (
                "Ensuite : saisie de la clé d'activation, puis configuration du commerce."
            )
        hint = QLabel(hint_text)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #94a3b8; font-size: 12px;")
        root.addWidget(hint)

        activate_and_center(self)

    def _build_card(
        self,
        code: str,
        title: str,
        description: str,
        *,
        current: str | None = None,
    ) -> QFrame:
        frame = QFrame()
        frame.setObjectName("ProductCard")
        is_current = bool(current and current == code)
        border = "#2563eb" if is_current else "#cbd5e1"
        frame.setStyleSheet(
            "#ProductCard {"
            f" border: {'2px' if is_current else '1px'} solid {border};"
            " border-radius: 12px; background: #ffffff;"
            "}"
            "#ProductCard:hover { border: 2px solid #2563eb; }"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        label = QLabel(title + (" (actuel)" if is_current else ""))
        label.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(label)

        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #64748b; font-size: 13px;")
        layout.addWidget(desc, 1)

        btn = QPushButton(
            f"Rester sur {title}" if is_current else f"Choisir {title}"
        )
        btn.setObjectName("Primary")
        btn.setMinimumHeight(40)
        btn.clicked.connect(lambda: self._choose(code))
        layout.addWidget(btn)
        return frame

    def _choose(self, code: str) -> None:
        product_profile.set_product(code)
        self.selected = code
        self.accept()
