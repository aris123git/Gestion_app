"""Caisse table — écran d'ajout de produits façon tablette (Maquis Caisse).

Cet écran remplace l'ancien parcours minimaliste (ouvrir une table puis
gérer via « Commandes ouvertes »). Il reproduit **point pour point** la
disposition de la caisse tablette :

* Catalogue à gauche : puces de catégories + grille de produits avec
  photos, dans un `QScrollArea` — le même code visuel que la POS caisse.
* Panier à droite : lignes éditables (quantité), suppression, note libre,
  bouton « + » sur chaque produit pour incrémenter, et bouton
  « Marquer payée » qui n'imprime **plus** aucun ticket.

Réutilisé par :

* ``TablesPage`` (clic sur une table libre ou occupée) ;
* ``OrdersPage`` (bouton « Ouvrir / Modifier »).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.controllers.category_controller import CategoryController
from app.controllers.product_controller import ProductController
from app.i18n import t
from app.services import order_service, settings_service
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import confirm, info, warn
from app.utils.helpers import format_money, format_quantity, to_float


class TableRegisterDialog(QDialog):
    """Interface caisse tablette pour une commande de table (Maquis Caisse)."""

    COL_NAME, COL_QTY, COL_PRICE, COL_TOTAL, COL_DEL = range(5)

    def __init__(self, order_id: int, parent=None):
        super().__init__(parent)
        self._order_id = int(order_id)
        self._order = order_service.OrderService.get(self._order_id)
        if self._order is None:
            raise ValueError("Commande introuvable.")
        self._grid_product_ids: list[int] = []
        self._chip_buttons: list[QToolButton] = []
        self._selected_category_id: Optional[int] = None
        self._updating_cart = False
        self._closed_paid = False

        title_bits = ["Caisse table"]
        if self._order.table is not None:
            title_bits.append(self._order.table.display_name)
        title_bits.append(self._order.public_id or f"CMD-{self._order.id}")
        self.setWindowTitle(" · ".join(title_bits))
        self.setModal(True)
        fit_dialog_to_screen(
            self,
            min_width=760,
            min_height=520,
            preferred_width=1180,
            preferred_height=780,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._build_catalog(), 5)
        body.addWidget(self._build_cart(), 4)
        root.addLayout(body, 1)

        root.addWidget(self._build_footer())

        self._reload_categories()
        self._reload_products()
        self._render_cart()

    # ------------------------------------------------------------------ header

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Card")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)

        table_txt = self._order.table.display_name if self._order.table else "Sans table"
        title = QLabel(f"<b>{table_txt}</b> — {self._order.public_id or 'CMD'}")
        title.setStyleSheet("font-size: 16px;")
        row.addWidget(title)

        row.addSpacing(20)
        row.addWidget(QLabel(t("Client :")))
        self.customer_edit = QLineEdit(self._order.customer_name or "")
        self.customer_edit.setPlaceholderText(t("Nom du client (optionnel)"))
        self.customer_edit.setMinimumWidth(180)
        self.customer_edit.editingFinished.connect(self._save_customer)
        row.addWidget(self.customer_edit, 1)

        row.addSpacing(12)
        row.addWidget(QLabel(t("Note :")))
        self.note_edit = QLineEdit(self._order.note or "")
        self.note_edit.setPlaceholderText(t("Ex. « sans oignons »"))
        self.note_edit.editingFinished.connect(self._save_note)
        row.addWidget(self.note_edit, 2)

        return bar

    # ----------------------------------------------------------------- catalog

    def _build_catalog(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel(t("Catalogue"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(t("Rechercher un produit…"))
        self.search_input.textChanged.connect(lambda _=None: self._reload_products())
        layout.addWidget(self.search_input)

        self.category_chips_scroll = QScrollArea()
        self.category_chips_scroll.setWidgetResizable(True)
        self.category_chips_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.category_chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.category_chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.category_chips_scroll.setFixedHeight(56)
        self.category_chips_host = QWidget()
        self.category_chips_layout = QHBoxLayout(self.category_chips_host)
        self.category_chips_layout.setContentsMargins(0, 0, 0, 0)
        self.category_chips_layout.setSpacing(8)
        self.category_chips_layout.addStretch(1)
        self.category_chips_scroll.setWidget(self.category_chips_host)
        layout.addWidget(self.category_chips_scroll)

        self.product_grid_scroll = QScrollArea()
        self.product_grid_scroll.setWidgetResizable(True)
        self.product_grid_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.product_grid_host = QWidget()
        self.product_grid_layout = QGridLayout(self.product_grid_host)
        self.product_grid_layout.setContentsMargins(4, 4, 4, 4)
        self.product_grid_layout.setSpacing(10)
        self.product_grid_scroll.setWidget(self.product_grid_host)
        layout.addWidget(self.product_grid_scroll, 1)

        return panel

    def _reload_categories(self) -> None:
        while self.category_chips_layout.count():
            item = self.category_chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._chip_buttons = []

        def make_chip(label: str, cat_id: Optional[int]) -> None:
            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            btn.setChecked(cat_id == self._selected_category_id)
            btn.setMinimumHeight(40)
            btn.setStyleSheet(
                "QToolButton { padding: 6px 14px; border-radius: 18px;"
                " border: 1px solid #cbd5e1; background: #f8fafc; }"
                "QToolButton:checked { background: #2563eb; color: white;"
                " border-color: #2563eb; }"
            )
            btn.clicked.connect(lambda _=False, cid=cat_id: self._select_category(cid))
            self.category_chips_layout.addWidget(btn)
            self._chip_buttons.append(btn)

        make_chip(t("Toutes"), None)
        for category in CategoryController.list():
            make_chip(category.name, category.id)
        self.category_chips_layout.addStretch(1)

    def _select_category(self, category_id: Optional[int]) -> None:
        self._selected_category_id = category_id
        self._reload_categories()
        self._reload_products()

    def _clear_product_grid(self) -> None:
        while self.product_grid_layout.count():
            item = self.product_grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._grid_product_ids = []

    def _make_product_card(self, product, currency: str) -> QFrame:
        card = QFrame()
        card.setObjectName("ProductCard")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setFixedSize(158, 194)
        card.setStyleSheet(
            "#ProductCard { border: 1px solid #e2e8f0; border-radius: 10px;"
            " background: #ffffff; }"
            "#ProductCard:hover { border: 2px solid #2563eb; }"
        )
        box = QVBoxLayout(card)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(4)

        img = QLabel()
        img.setFixedSize(140, 100)
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img.setStyleSheet(
            "background: #f1f5f9; border-radius: 6px; color: #94a3b8;"
        )
        path = str(getattr(product, "image_path", "") or "")
        pix = QPixmap(path) if path else QPixmap()
        if not pix.isNull():
            img.setPixmap(
                pix.scaled(
                    140,
                    100,
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

        price = QLabel(format_money(product.sale_price, currency))
        price.setAlignment(Qt.AlignmentFlag.AlignCenter)
        price.setStyleSheet("color: #0f172a; font-weight: 700;")
        box.addWidget(price)

        pid = product.id

        def _click(_event=None, product_id=pid):
            self._add_product(product_id)

        card.mousePressEvent = _click
        return card

    def _reload_products(self) -> None:
        products = ProductController.list(
            search=self.search_input.text().strip(),
            category_id=self._selected_category_id,
        )
        currency = settings_service.get_currency()
        self._clear_product_grid()
        cols = 4
        for index, product in enumerate(products):
            if getattr(product, "free_amount_sale", False):
                continue
            if getattr(product, "sale_price", 0) is None or float(product.sale_price or 0) <= 0:
                continue
            card = self._make_product_card(product, currency)
            self.product_grid_layout.addWidget(card, index // cols, index % cols)
            self._grid_product_ids.append(product.id)
        self.product_grid_layout.setRowStretch(
            (len(self._grid_product_ids) + cols - 1) // cols, 1
        )

    # -------------------------------------------------------------------- cart

    def _build_cart(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel(t("Commande en cours"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        self.cart_table = QTableWidget(0, 5)
        self.cart_table.setHorizontalHeaderLabels(
            [t("Produit"), t("Qté"), t("Prix U."), t("Total"), ""]
        )
        self.cart_table.horizontalHeader().setSectionResizeMode(
            self.COL_NAME, QHeaderView.ResizeMode.Stretch
        )
        self.cart_table.setColumnWidth(self.COL_QTY, 72)
        self.cart_table.setColumnWidth(self.COL_PRICE, 96)
        self.cart_table.setColumnWidth(self.COL_TOTAL, 108)
        self.cart_table.setColumnWidth(self.COL_DEL, 46)
        self.cart_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cart_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.cart_table.verticalHeader().setDefaultSectionSize(38)
        self.cart_table.verticalHeader().setVisible(False)
        self.cart_table.itemChanged.connect(self._on_cart_edited)
        layout.addWidget(self.cart_table, 1)

        self.total_label = QLabel("")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.total_label.setStyleSheet("font-size: 24px; font-weight: 800;")
        layout.addWidget(self.total_label)

        return panel

    def _render_cart(self) -> None:
        self._updating_cart = True
        currency = settings_service.get_currency()
        items = list(self._order.items or [])
        self.cart_table.setRowCount(len(items))
        for row, line in enumerate(items):
            name_item = QTableWidgetItem(line.product_name or f"#{line.product_id or '?'}")
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setData(Qt.ItemDataRole.UserRole, int(line.id))

            qty_item = QTableWidgetItem(format_quantity(float(line.quantity)))
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            qty_item.setData(Qt.ItemDataRole.UserRole, int(line.id))

            price_item = QTableWidgetItem(format_money(float(line.unit_price), currency))
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            price_item.setFlags(price_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            total_item = QTableWidgetItem(format_money(float(line.line_total), currency))
            total_item.setFlags(total_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            total_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

            self.cart_table.setItem(row, self.COL_NAME, name_item)
            self.cart_table.setItem(row, self.COL_QTY, qty_item)
            self.cart_table.setItem(row, self.COL_PRICE, price_item)
            self.cart_table.setItem(row, self.COL_TOTAL, total_item)

            del_btn = QPushButton("✕")
            del_btn.setObjectName("Danger")
            del_btn.setToolTip(t("Retirer cette ligne"))
            del_btn.clicked.connect(
                lambda _=False, item_id=int(line.id): self._remove_line(item_id)
            )
            self.cart_table.setCellWidget(row, self.COL_DEL, del_btn)

        self.total_label.setText(
            t("Total : ") + format_money(float(self._order.total or 0), currency)
        )
        self._updating_cart = False

    def _on_cart_edited(self, item: QTableWidgetItem) -> None:
        if self._updating_cart:
            return
        if item.column() != self.COL_QTY:
            return
        item_id_raw = item.data(Qt.ItemDataRole.UserRole)
        try:
            item_id = int(item_id_raw)
        except (TypeError, ValueError):
            return
        qty = to_float(item.text())
        try:
            if qty <= 0:
                if not confirm(
                    self,
                    t("Retirer cette ligne de la commande ?"),
                    t("Commande"),
                ):
                    self._order = order_service.OrderService.get(self._order_id) or self._order
                    self._render_cart()
                    return
                self._order = order_service.OrderService.remove_item(self._order_id, item_id)
            else:
                self._order = order_service.OrderService.update_item_quantity(
                    self._order_id, item_id, qty
                )
        except ValueError as exc:
            warn(self, str(exc))
            self._order = order_service.OrderService.get(self._order_id) or self._order
        self._render_cart()

    def _remove_line(self, item_id: int) -> None:
        try:
            self._order = order_service.OrderService.remove_item(self._order_id, item_id)
        except ValueError as exc:
            warn(self, str(exc))
            return
        self._render_cart()

    def _add_product(self, product_id: int) -> None:
        product = ProductController.get(product_id)
        if product is None:
            warn(self, t("Produit introuvable."))
            return
        price = float(product.sale_price or 0)
        if price <= 0:
            warn(
                self,
                t("Ce produit n'a pas de prix de vente configuré."),
                t("Prix manquant"),
            )
            return
        try:
            self._order = order_service.OrderService.add_item(
                self._order_id,
                product_id=int(product.id),
                product_name=product.name,
                quantity=1.0,
                unit_price=price,
                merge=True,
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        self._render_cart()

    # ------------------------------------------------------------------ footer

    def _build_footer(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Card")
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(10)

        hint = QLabel(
            t(
                "« Marquer payée » n'imprime plus le ticket automatiquement — la table est simplement libérée."
            )
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b; font-size: 12px;")
        row.addWidget(hint, 1)

        cancel = QPushButton(t("Annuler commande"))
        cancel.setToolTip(t("Annule la commande et libère la table."))
        cancel.clicked.connect(self._cancel_order)
        row.addWidget(cancel)

        close = QPushButton(t("Fermer"))
        close.setToolTip(t("Garde la commande ouverte et revient à la salle."))
        close.clicked.connect(self.reject)
        row.addWidget(close)

        pay = QPushButton(t("Marquer payée"))
        pay.setObjectName("Success")
        pay.setMinimumHeight(46)
        pay.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        pay.clicked.connect(self._mark_paid)
        row.addWidget(pay)

        return bar

    # ------------------------------------------------------------- persistence

    def _save_customer(self) -> None:
        value = self.customer_edit.text().strip()
        if value == (self._order.customer_name or ""):
            return
        try:
            self._order = order_service.OrderService.set_customer_name(
                self._order_id, value
            )
        except ValueError as exc:
            warn(self, str(exc))

    def _save_note(self) -> None:
        value = self.note_edit.text().strip()
        if value == (self._order.note or ""):
            return
        try:
            self._order = order_service.OrderService.set_note(self._order_id, value)
        except ValueError as exc:
            warn(self, str(exc))

    def _cancel_order(self) -> None:
        if not confirm(
            self,
            t("Annuler cette commande ? Les lignes seront supprimées."),
            t("Annuler commande"),
        ):
            return
        try:
            order_service.OrderService.cancel(self._order_id)
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.reject()

    def _mark_paid(self) -> None:
        items = list(self._order.items or [])
        if not items:
            warn(self, t("Ajoutez au moins un produit avant d'encaisser."))
            return
        currency = settings_service.get_currency()
        message = (
            t("Marquer cette commande comme payée ?")
            + "\n\n"
            + t("Total : ")
            + format_money(float(self._order.total or 0), currency)
            + "\n\n"
            + t("Aucun ticket ne sera imprimé automatiquement.")
        )
        if not confirm(self, message, t("Encaissement")):
            return
        try:
            order_service.OrderService.mark_paid(self._order_id)
        except ValueError as exc:
            warn(self, str(exc))
            return
        self._closed_paid = True
        info(
            self,
            t("Commande payée — table libérée si aucune autre commande n'y est ouverte."),
            t("Encaissement"),
        )
        self.accept()

    @property
    def order_closed_paid(self) -> bool:
        return self._closed_paid
