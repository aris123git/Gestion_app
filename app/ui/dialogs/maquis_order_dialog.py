"""Éditeur tactile d'une commande Maquis, partagé par Tables et Commandes."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.controllers.category_controller import CategoryController
from app.controllers.product_controller import ProductController
from app.services import order_service, settings_service
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import warn
from app.utils.helpers import format_money, format_quantity


class MaquisOrderDialog(QDialog):
    """Catalogue en cartes + addition tactile, comme sur la tablette Maquis."""

    order_changed = Signal()

    def __init__(self, order_id: int, parent=None):
        super().__init__(parent)
        self.order_id = int(order_id)
        self.order = None
        self.currency = settings_service.get_currency()
        self._product_buttons: list[QPushButton] = []
        self.setWindowTitle("Commande Maquis")
        self.setModal(True)
        fit_dialog_to_screen(
            self,
            min_width=760,
            min_height=520,
            preferred_width=1180,
            preferred_height=760,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("PageTitle")
        header.addWidget(self.title)
        header.addStretch()
        self.total_badge = QLabel()
        self.total_badge.setStyleSheet(
            "background:#0f172a;color:white;border-radius:12px;"
            "padding:10px 18px;font-size:20px;font-weight:800;"
        )
        header.addWidget(self.total_badge)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._build_catalog(), 3)
        body.addWidget(self._build_order_panel(), 2)
        root.addLayout(body, 1)

        footer = QHBoxLayout()
        hint = QLabel("Touchez un produit pour l'ajouter à la commande.")
        hint.setStyleSheet("color:#64748b;")
        footer.addWidget(hint)
        footer.addStretch()
        close = QPushButton("Terminer")
        close.setObjectName("Primary")
        close.setMinimumHeight(44)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        root.addLayout(footer)

        self._load_categories()
        self.refresh()

    def _build_catalog(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        label = QLabel("Produits")
        label.setObjectName("SectionTitle")
        layout.addWidget(label)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher un produit…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._reload_products)
        self.category = QComboBox()
        self.category.currentIndexChanged.connect(self._reload_products)
        filters.addWidget(self.search, 3)
        filters.addWidget(self.category, 2)
        layout.addLayout(filters)

        self.product_scroll = QScrollArea()
        self.product_scroll.setWidgetResizable(True)
        self.product_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.product_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.product_host = QWidget()
        self.product_grid = QGridLayout(self.product_host)
        self.product_grid.setContentsMargins(2, 2, 2, 2)
        self.product_grid.setSpacing(10)
        self.product_scroll.setWidget(self.product_host)
        layout.addWidget(self.product_scroll, 1)
        return panel

    def _build_order_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        label = QLabel("Addition")
        label.setObjectName("SectionTitle")
        layout.addWidget(label)
        self.customer = QLineEdit()
        self.customer.setPlaceholderText("Nom du client (facultatif)")
        self.customer.editingFinished.connect(self._save_details)
        layout.addWidget(self.customer)

        self.lines_scroll = QScrollArea()
        self.lines_scroll.setWidgetResizable(True)
        self.lines_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.lines_host = QWidget()
        self.lines_layout = QVBoxLayout(self.lines_host)
        self.lines_layout.setContentsMargins(0, 0, 4, 0)
        self.lines_layout.setSpacing(8)
        self.lines_scroll.setWidget(self.lines_host)
        layout.addWidget(self.lines_scroll, 1)

        self.note = QLineEdit()
        self.note.setPlaceholderText("Note cuisine / service…")
        self.note.editingFinished.connect(self._save_details)
        layout.addWidget(self.note)
        return panel

    def _load_categories(self) -> None:
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("Toutes les catégories", None)
        for category in CategoryController.list():
            self.category.addItem(category.name, category.id)
        self.category.blockSignals(False)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _reload_products(self) -> None:
        self._clear_layout(self.product_grid)
        self._product_buttons = []
        products = ProductController.list(
            search=self.search.text().strip(),
            category_id=self.category.currentData(),
        )
        columns = 3
        for index, product in enumerate(products):
            button = QPushButton()
            button.setMinimumSize(150, 132)
            button.setMaximumHeight(150)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            stock = f"Stock {format_quantity(product.quantity)}"
            button.setText(
                f"{product.name}\n\n"
                f"{format_money(float(product.sale_price), self.currency)}\n{stock}"
            )
            button.setStyleSheet(
                "QPushButton { text-align:center;padding:10px;border-radius:12px;"
                "font-size:14px;font-weight:700;background:#ffffff;"
                "border:1px solid #cbd5e1; }"
                "QPushButton:hover { border:2px solid #2563eb;background:#eff6ff; }"
                "QPushButton:disabled { background:#f1f5f9;color:#94a3b8; }"
            )
            image_path = str(getattr(product, "image_path", "") or "")
            pixmap = QPixmap(image_path) if image_path else QPixmap()
            if not pixmap.isNull():
                button.setIcon(
                    QIcon(
                        pixmap.scaled(
                            56,
                            56,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                )
                button.setIconSize(pixmap.size().boundedTo(button.size()))
            button.setEnabled(float(product.quantity or 0) > 0)
            button.setToolTip(
                f"{product.name} — {stock}"
                + (" (rupture)" if float(product.quantity or 0) <= 0 else "")
            )
            button.clicked.connect(
                lambda _=False, product_id=product.id: self._add_product(product_id)
            )
            self.product_grid.addWidget(button, index // columns, index % columns)
            self._product_buttons.append(button)
        row = (len(products) + columns - 1) // columns
        self.product_grid.setRowStretch(row, 1)

    def _add_product(self, product_id: int) -> None:
        product = ProductController.get(product_id)
        if not product:
            warn(self, "Produit introuvable.")
            return
        in_order = sum(
            float(item.quantity)
            for item in (self.order.items if self.order else [])
            if item.product_id == product.id
        )
        if in_order + 1 > float(product.quantity or 0) + 0.0001:
            warn(
                self,
                f"Stock insuffisant pour « {product.name} » "
                f"(disponible : {format_quantity(product.quantity)}).",
                "Stock insuffisant",
            )
            return
        try:
            order_service.OrderService.add_item(
                self.order_id,
                product_id=product.id,
                product_name=product.name,
                quantity=1,
                unit_price=float(product.sale_price),
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()
        self.order_changed.emit()

    def _change_quantity(self, item_id: int, value: int) -> None:
        try:
            order_service.OrderService.set_item_quantity(
                self.order_id, item_id, value
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()
        self.order_changed.emit()

    def _remove_item(self, item_id: int) -> None:
        try:
            order_service.OrderService.remove_item(self.order_id, item_id)
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()
        self.order_changed.emit()

    def _render_lines(self) -> None:
        self._clear_layout(self.lines_layout)
        if not self.order or not self.order.items:
            empty = QLabel("Aucun produit\n\nTouchez un produit à gauche.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(
                "color:#94a3b8;padding:36px;border:1px dashed #cbd5e1;"
                "border-radius:12px;"
            )
            self.lines_layout.addWidget(empty)
            self.lines_layout.addStretch(1)
            return
        for item in self.order.items:
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background:#f8fafc;border:1px solid #e2e8f0;"
                "border-radius:10px; } QLabel { border:none;background:transparent; }"
            )
            box = QVBoxLayout(card)
            box.setContentsMargins(10, 8, 10, 8)
            top = QHBoxLayout()
            name = QLabel(item.product_name)
            name.setStyleSheet("font-weight:700;")
            name.setWordWrap(True)
            total = QLabel(format_money(float(item.line_total), self.currency))
            total.setStyleSheet("font-weight:800;color:#0f172a;")
            top.addWidget(name, 1)
            top.addWidget(total)
            box.addLayout(top)

            controls = QHBoxLayout()
            unit = QLabel(
                f"{format_quantity(item.quantity)} × "
                f"{format_money(float(item.unit_price), self.currency)}"
            )
            unit.setStyleSheet("color:#64748b;")
            controls.addWidget(unit, 1)
            minus = QPushButton("−")
            minus.setFixedSize(38, 36)
            minus.clicked.connect(
                lambda _=False, iid=item.id, qty=float(item.quantity): (
                    self._change_quantity(iid, max(0, int(qty) - 1))
                )
            )
            plus = QPushButton("+")
            plus.setFixedSize(38, 36)
            plus.setObjectName("Primary")
            plus.clicked.connect(
                lambda _=False, iid=item.id, qty=float(item.quantity): (
                    self._change_quantity(iid, int(qty) + 1)
                )
            )
            remove = QPushButton("✕")
            remove.setFixedSize(38, 36)
            remove.setObjectName("Danger")
            remove.clicked.connect(
                lambda _=False, iid=item.id: self._remove_item(iid)
            )
            controls.addWidget(minus)
            controls.addWidget(plus)
            controls.addWidget(remove)
            box.addLayout(controls)
            self.lines_layout.addWidget(card)
        self.lines_layout.addStretch(1)

    def _save_details(self) -> None:
        if not self.order:
            return
        try:
            order_service.OrderService.update_details(
                self.order_id,
                customer_name=self.customer.text(),
                note=self.note.text(),
            )
            self.order_changed.emit()
        except ValueError as exc:
            warn(self, str(exc))

    def refresh(self) -> None:
        order = order_service.OrderService.get(self.order_id)
        if not order:
            warn(self, "Commande introuvable.")
            self.reject()
            return
        self.order = order
        table_name = order.table.display_name if order.table else "Sans table"
        self.title.setText(f"{order.public_id} · {table_name}")
        self.total_badge.setText(format_money(float(order.total or 0), self.currency))
        if not self.customer.hasFocus():
            self.customer.setText(order.customer_name or "")
        if not self.note.hasFocus():
            self.note.setText(order.note or "")
        self._render_lines()
        self._reload_products()

    def accept(self) -> None:
        self._save_details()
        super().accept()
