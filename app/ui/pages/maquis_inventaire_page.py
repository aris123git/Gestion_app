"""Page inventaire Maquis — comptage produit par produit (parité tablette)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.controllers.product_controller import ProductController
from app.i18n import t
from app.services.maquis_inventaire_service import InventaireEcartReason, apply_inventory_count
from app.ui.state import AppState
from app.ui.widgets.helpers import info, page_title, warn


class _GapDialog(QDialog):
    def __init__(self, product_name: str, theoretical: float, counted: float, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Écart inventaire"))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{product_name}"))
        layout.addWidget(
            QLabel(f"{t('Théorique')} {theoretical:g} · {t('Compté')} {counted:g}")
        )
        self.reason = QComboBox()
        for r in (
            InventaireEcartReason.PERTE,
            InventaireEcartReason.CASSE,
            InventaireEcartReason.VENTE_HORS_CAISSE,
            InventaireEcartReason.ERREUR_SAISIE,
            InventaireEcartReason.AUTRE,
        ):
            self.reason.addItem(r.label, r)
        layout.addWidget(self.reason)
        self.comment = QLineEdit()
        self.comment.setPlaceholderText(t("Commentaire"))
        layout.addWidget(self.comment)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MaquisInventairePage(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._counts: dict[int, float] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.addWidget(page_title(t("Inventaire")))
        root.addWidget(
            QLabel(t("Comptage tactile — écarts tracés (NexaGes Maquis)"))
        )
        self._message = QLabel("")
        self._message.setWordWrap(True)
        root.addWidget(self._message)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._host = QWidget()
        self._list_layout = QVBoxLayout(self._host)
        self._list_layout.setSpacing(10)
        scroll.setWidget(self._host)
        root.addWidget(scroll, 1)

    def refresh(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        products = ProductController.list(only_active=True)
        for product in products:
            self._list_layout.addWidget(self._row(product))

    def _row(self, product) -> QWidget:
        card = QWidget()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.addWidget(QLabel(f"<b>{product.name}</b>"))
        theoretical = float(product.quantity or 0)
        layout.addWidget(QLabel(f"{t('Stock théorique')} : {theoretical:g}"))
        row = QHBoxLayout()
        minus = QPushButton("−")
        minus.setFixedWidth(48)
        spin = QDoubleSpinBox()
        spin.setDecimals(3)
        spin.setMaximum(1_000_000)
        spin.setValue(self._counts.get(product.id, theoretical))
        plus = QPushButton("+")
        plus.setFixedWidth(48)

        def sync(val: float) -> None:
            self._counts[product.id] = val

        spin.valueChanged.connect(sync)
        minus.clicked.connect(lambda: spin.setValue(max(0.0, spin.value() - 1)))
        plus.clicked.connect(lambda: spin.setValue(spin.value() + 1))
        row.addWidget(minus)
        row.addWidget(spin, 1)
        row.addWidget(plus)
        layout.addLayout(row)
        gap_label = QLabel("")
        layout.addWidget(gap_label)

        def update_gap() -> None:
            gap = spin.value() - theoretical
            if abs(gap) < 0.0001:
                gap_label.setText("")
            else:
                sign = "+" if gap > 0 else ""
                gap_label.setText(f"{t('Écart')} : {sign}{gap:g}")

        spin.valueChanged.connect(lambda _: update_gap())
        update_gap()

        btn = QPushButton(t("Valider le comptage"))
        btn.setObjectName("Primary")

        def validate() -> None:
            counted = float(spin.value())
            gap = counted - theoretical
            reason = None
            comment = None
            if gap < -0.0001:
                dlg = _GapDialog(product.name, theoretical, counted, self)
                if dlg.exec() != QDialog.DialogCode.Accepted:
                    return
                reason = dlg.reason.currentData()
                comment = dlg.comment.text().strip() or None
            try:
                msg = apply_inventory_count(
                    product.id,
                    product.name,
                    theoretical,
                    counted,
                    reason=reason,
                    comment=comment,
                    user_id=self.state.user_id,
                    unit_price=float(product.sale_price or 0),
                    purchase_price=float(product.purchase_price or 0),
                )
                self._message.setText(msg)
                info(self, msg)
                self._counts[product.id] = counted
                self.refresh()
            except Exception as exc:
                warn(self, str(exc))

        btn.clicked.connect(validate)
        layout.addWidget(btn)
        return card
