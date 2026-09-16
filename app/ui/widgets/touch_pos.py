"""Composants tactiles partagés (style tablette Maquis Caisse).

Utilisés à l'identique par la caisse (POSPage) et par l'écran de commande
d'une table (MaquisOrderDialog) pour garantir un rendu « point pour point »
entre les deux écrans : mêmes vignettes produits, mêmes puces de catégories,
même stepper − quantité +.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.utils.helpers import format_money

CHIP_STYLE = (
    "QToolButton { padding: 6px 14px; border-radius: 18px;"
    " border: 1px solid #cbd5e1; background: #f8fafc; }"
    "QToolButton:checked { background: #2563eb; color: white;"
    " border-color: #2563eb; }"
)

CARD_STYLE = (
    "#ProductCard { border: 1px solid #e2e8f0; border-radius: 10px;"
    " background: #ffffff; }"
    "#ProductCard:hover { border: 2px solid #2563eb; }"
)

STEPPER_BTN_STYLE = (
    "QPushButton { border: 1px solid #cbd5e1; border-radius: 6px;"
    " background: #f8fafc; font-weight: 700; }"
    "QPushButton:pressed { background: #e2e8f0; }"
)


def make_category_chip(
    label: str,
    checked: bool,
    on_click: Callable[[], None],
    tooltip: str = "",
) -> QToolButton:
    """Puce de catégorie tactile, identique caisse / commande table."""
    btn = QToolButton()
    btn.setText(label)
    btn.setCheckable(True)
    btn.setChecked(checked)
    btn.setMinimumHeight(40)
    btn.setStyleSheet(CHIP_STYLE)
    btn.clicked.connect(lambda _=False: on_click())
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


def make_product_card(
    product,
    currency: str,
    on_click: Callable[[int], None],
) -> QFrame:
    """Vignette produit tactile (image, nom, prix) — style tablette."""
    card = QFrame()
    card.setObjectName("ProductCard")
    card.setCursor(Qt.CursorShape.PointingHandCursor)
    card.setFixedSize(148, 180)
    card.setStyleSheet(CARD_STYLE)
    box = QVBoxLayout(card)
    box.setContentsMargins(8, 8, 8, 8)
    box.setSpacing(4)
    img = QLabel()
    img.setFixedSize(128, 96)
    img.setAlignment(Qt.AlignmentFlag.AlignCenter)
    img.setStyleSheet("background: #f1f5f9; border-radius: 6px; color: #94a3b8;")
    path = str(getattr(product, "image_path", "") or "")
    pix = QPixmap(path) if path else QPixmap()
    if not pix.isNull():
        img.setPixmap(
            pix.scaled(
                128,
                96,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
    else:
        img.setText("•")
    box.addWidget(img, alignment=Qt.AlignmentFlag.AlignCenter)
    name = QLabel(product.name)
    name.setWordWrap(True)
    name.setAlignment(Qt.AlignmentFlag.AlignCenter)
    name.setStyleSheet("font-weight: 600; font-size: 12px;")
    box.addWidget(name)
    if getattr(product, "free_amount_sale", False):
        price_txt = (
            f"réf. {format_money(product.sale_price, currency)}"
            if float(product.sale_price or 0) > 0
            else "montant libre"
        )
    else:
        price_txt = format_money(product.sale_price, currency)
    price = QLabel(price_txt)
    price.setAlignment(Qt.AlignmentFlag.AlignCenter)
    price.setStyleSheet("color: #0f172a; font-weight: 700;")
    box.addWidget(price)
    pid = product.id

    def _click(_event=None, product_id=pid):
        on_click(product_id)

    card.mousePressEvent = _click
    return card


def make_qty_stepper(
    qty_text: str,
    on_minus: Callable[[], None],
    on_plus: Callable[[], None],
    on_edit: Optional[Callable[[], None]] = None,
) -> QWidget:
    """Stepper tactile « − qté + » pour le panier / la commande de table."""
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(2, 2, 2, 2)
    row.setSpacing(2)
    minus = QPushButton("−")
    minus.setFixedSize(26, 26)
    minus.setStyleSheet(STEPPER_BTN_STYLE)
    minus.clicked.connect(lambda _=False: on_minus())
    qty = QPushButton(qty_text)
    qty.setFlat(True)
    qty.setMinimumWidth(28)
    qty.setStyleSheet(
        "QPushButton { border: none; background: transparent; font-weight: 700; }"
    )
    if on_edit is not None:
        qty.setCursor(Qt.CursorShape.PointingHandCursor)
        qty.setToolTip("Cliquez pour saisir la quantité")
        qty.clicked.connect(lambda _=False: on_edit())
    plus = QPushButton("+")
    plus.setFixedSize(26, 26)
    plus.setStyleSheet(STEPPER_BTN_STYLE)
    plus.clicked.connect(lambda _=False: on_plus())
    row.addStretch(1)
    row.addWidget(minus)
    row.addWidget(qty)
    row.addWidget(plus)
    row.addStretch(1)
    return host
