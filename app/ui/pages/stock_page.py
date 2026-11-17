"""Page de gestion du stock : entrées, sorties, inventaire, corrections, historique."""
from __future__ import annotations
from app.i18n import t
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget
from app.controllers.product_controller import ProductController
from app.controllers.stock_controller import StockController
from app.controllers.supplier_controller import SupplierController
from app.services import audit_service, permissions as perms
from app.services.inventory_service import InventoryService
from app.ui.responsive import LayoutProfile, STOCK_HISTORY_COLUMNS, TableColumnController
from app.ui.state import AppState
from app.ui.widgets.helpers import info, make_card, page_title, warn
from app.utils.helpers import format_datetime, format_quantity
from app.ui.widgets.money_spin import MoneySpinBox

class StockPage(QWidget):
    HISTORY_LIMIT = 1000
    HISTORY_HEADERS = ['Date', 'Utilisateur', 'Produit', 'Mouvement', 'Quantité', 'Stock après', 'Fournisseur', 'N° facture', 'Motif', 'Commentaire']

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(page_title(t('Gestion du stock')))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_movement_tab(), t('Mouvements'))
        self.tabs.addTab(self._build_history_tab(), t('Historique'))
        self.tabs.currentChanged.connect(lambda _: self._reload_history())
        layout.addWidget(self.tabs)

    ACTIONS = [
        ('in', 'Entrée +', 'Quantité reçue', ('supplier', 'invoice', 'cost', 'price', 'comment'), "Enregistrer l'entrée"),
        ('out', 'Sortie −', 'Quantité sortie', ('reason', 'comment'), 'Enregistrer la sortie'),
        ('loss', 'Perte', 'Quantité perdue', ('loss', 'comment'), 'Enregistrer la perte'),
        ('inv', 'Inventaire =', 'Quantité comptée', ('reason', 'comment'), "Enregistrer l'inventaire"),
        ('fix', 'Correction', 'Nouveau stock', ('reason', 'comment'), 'Enregistrer la correction'),
    ]

    def _build_movement_tab(self) -> QWidget:
        wrap = QWidget()
        outer = QHBoxLayout(wrap)
        outer.setContentsMargins(0, 12, 0, 0)
        outer.setSpacing(12)
        # -- gauche : produits ---------------------------------------------------------------------------
        left = QVBoxLayout()
        self.product_search = QLineEdit()
        self.product_search.setPlaceholderText(t('Rechercher un produit…'))
        self.product_search.textChanged.connect(self._reload_products)
        left.addWidget(self.product_search)
        self.product_table = QTableWidget(0, 3)
        self.product_table.setHorizontalHeaderLabels([t('Produit'), t('Stock'), t('Alerte')])
        self.product_table.verticalHeader().setVisible(False)
        self.product_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.product_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.product_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.product_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.product_table.currentCellChanged.connect(lambda *_: self._show_product())
        left.addWidget(self.product_table, 1)
        outer.addLayout(left, 3)
        # -- droite : action et champs utiles ---------------------------------------------------------------
        side = QVBoxLayout()
        self.p_head = QLabel(t('Sélectionnez un produit.'))
        self.p_head.setTextFormat(Qt.TextFormat.RichText)
        self.p_head.setWordWrap(True)
        side.addWidget(self.p_head)
        chips = QHBoxLayout()
        self._action = 'in'
        self._action_buttons = {}
        for key, label, _qty_label, _fields, _cta in self.ACTIONS:
            b = QPushButton(t(label))
            b.setCheckable(True)
            b.setStyleSheet('QPushButton:checked { background: #2563eb; color: #ffffff; border-color: #2563eb; }')
            b.clicked.connect(lambda _=False, k=key: self._set_action(k))
            self._action_buttons[key] = b
            chips.addWidget(b)
        side.addLayout(chips)
        form_widget = QWidget()
        form_widget.setObjectName('Plain')
        form = QFormLayout(form_widget)
        form.setSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.quantity = QDoubleSpinBox()
        self.quantity.setRange(0, 10000000)
        self.quantity.setDecimals(3)
        self.quantity.valueChanged.connect(self._update_preview)
        self.supplier_combo = QComboBox()
        self.unit_cost = MoneySpinBox()
        self.unit_cost.setRange(0, 1000000000)
        self.unit_cost.setDecimals(3)
        self.new_sale_price = MoneySpinBox()
        self.new_sale_price.setRange(0, 1000000000)
        self.new_sale_price.setDecimals(3)
        self.new_sale_price.setToolTip(t("Optionnel. Si de l'ancien stock reste, ce prix ne s'appliquera qu'après sa vente complète. 0 = ne pas changer."))
        self.invoice_number = QLineEdit()
        self.invoice_number.setPlaceholderText(t('Facultatif'))
        self.reason = QLineEdit()
        self.loss_reason = QComboBox()
        self.loss_reason.addItems(InventoryService.loss_reasons())
        self.comment = QLineEdit()
        self.comment.setPlaceholderText(t('Facultatif'))
        self._qty_label = QLabel()
        self._fields = {'supplier': (t('Fournisseur'), self.supplier_combo), 'invoice': (t('N° facture'), self.invoice_number),
                        'cost': (t('Coût unitaire'), self.unit_cost), 'price': (t('Nouveau prix de vente'), self.new_sale_price),
                        'reason': (t('Motif'), self.reason), 'loss': (t('Motif de perte'), self.loss_reason), 'comment': (t('Commentaire'), self.comment)}
        form.addRow(self._qty_label, self.quantity)
        self._field_labels = {}
        for key in ('supplier', 'invoice', 'cost', 'price', 'reason', 'loss', 'comment'):
            label, widget = self._fields[key]
            form.addRow(label, widget)
            self._field_labels[key] = form.labelForField(widget)
        side.addWidget(make_card(form_widget))
        self.preview = QLabel()
        self.preview.setTextFormat(Qt.TextFormat.RichText)
        side.addWidget(self.preview)
        self.save_button = QPushButton()
        self.save_button.setObjectName('Primary')
        self.save_button.clicked.connect(self._save)
        side.addWidget(self.save_button)
        side.addStretch()
        outer.addLayout(side, 2)
        self._set_action('in')
        return wrap

    def _set_action(self, key: str) -> None:
        self._action = key
        spec = next(a for a in self.ACTIONS if a[0] == key)
        for k, b in self._action_buttons.items():
            b.setChecked(k == key)
        self._qty_label.setText(t(spec[2]))
        for fkey, (_label, widget) in self._fields.items():
            visible = fkey in spec[3]
            widget.setVisible(visible)
            self._field_labels[fkey].setVisible(visible)
        self.reason.setPlaceholderText(t({'out': 'Ex. : Usage personnel', 'inv': 'Ex. : Inventaire de fin de mois', 'fix': 'Obligatoire. Ex. : erreur de saisie'}.get(key, '')))
        self.save_button.setText(t(spec[4]))
        self._update_preview()

    def _selected_product(self):
        row = self.product_table.currentRow()
        pid = self.product_table.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 and self.product_table.item(row, 0) else None
        return next((p for p in getattr(self, '_products', []) if p.id == pid), None)

    def _show_product(self) -> None:
        product = self._selected_product()
        if product is None:
            self.p_head.setText(t('Sélectionnez un produit.'))
        else:
            color = '#b91c1c' if product.is_out_of_stock or product.is_low_stock else '#0f172a'
            self.p_head.setText(f"<b style='font-size:15px'>{product.name}</b><br><span style='color:{color}'><b>{t('Stock actuel')} : {format_quantity(product.quantity)}</b></span>"
                                f" <span style='color:#64748b'>({t('minimum')} {format_quantity(product.min_stock or 0)})</span>")
        self.save_button.setEnabled(product is not None)
        self._update_preview()

    def _update_preview(self, *_a) -> None:
        product = self._selected_product()
        if product is None:
            self.preview.setText('')
            return
        cur, q = float(product.quantity or 0), self.quantity.value()
        after = {'in': cur + q, 'out': cur - q, 'loss': cur - q, 'inv': q, 'fix': q}[self._action]
        self.preview.setText(f"<span style='color:#64748b'>{t('Stock après')} : </span><b>{format_quantity(after)}</b>")

    def _current_product_id(self):
        product = self._selected_product()
        return product.id if product else None

    def _current_supplier_id(self):
        return self.supplier_combo.currentData()

    def _save(self) -> None:
        {'in': self._stock_in, 'out': self._stock_out, 'loss': self._record_loss, 'inv': self._inventory, 'fix': self._correction}[self._action]()

    def _build_history_tab(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 12, 0, 0)
        bar = QHBoxLayout()
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText(t('Rechercher un produit…'))
        self.history_search.textChanged.connect(self._reload_history)
        self.history_type = QComboBox()
        self.history_type.addItem(t('Tous les mouvements'), None)
        self.history_type.currentIndexChanged.connect(self._reload_history)
        bar.addWidget(self.history_search, 1)
        bar.addWidget(self.history_type)
        layout.addLayout(bar)
        self.history_note = QLabel('')
        self.history_note.setStyleSheet('color: #b45309; font-size: 12px;')
        self.history_note.setWordWrap(True)
        layout.addWidget(self.history_note)
        self.history_table = QTableWidget(0, len(self.HISTORY_HEADERS))
        self.history_table.setHorizontalHeaderLabels(self.HISTORY_HEADERS)
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.history_table)
        self._history_columns = TableColumnController(self.history_table, STOCK_HISTORY_COLUMNS)
        self.state.layout_changed.connect(self._on_layout_changed)
        if self.state.layout is not None:
            self._on_layout_changed(self.state.layout)
        return wrap

    def _on_layout_changed(self, profile: LayoutProfile) -> None:
        if hasattr(self, '_history_columns'):
            self._history_columns.apply(profile.content_width)

    def _ensure_stock_permission(self) -> bool:
        if self.state.can(perms.MANAGE_STOCK):
            return True
        warn(self, t("Vous n'avez pas l'autorisation de modifier le stock."))
        return False

    def _stock_in(self) -> None:
        if not self._ensure_stock_permission():
            return
        pid = self._current_product_id()
        if not pid or self.quantity.value() <= 0:
            warn(self, t('Choisissez un produit et une quantité.'))
            return
        motif = self.reason.text().strip() or 'Livraison fournisseur'
        StockController.stock_in(pid, self.quantity.value(), self.unit_cost.value(), motif, self.state.user_id, supplier_id=self._current_supplier_id(), invoice_number=self.invoice_number.text(), comment=self.comment.text(), new_sale_price=self.new_sale_price.value())
        self._after_movement('Entrée de stock', pid)

    def _stock_out(self) -> None:
        if not self._ensure_stock_permission():
            return
        pid = self._current_product_id()
        if not pid or self.quantity.value() <= 0:
            warn(self, t('Choisissez un produit et une quantité.'))
            return
        StockController.stock_out(pid, self.quantity.value(), self.reason.text().strip() or 'Sortie de stock', self.state.user_id, comment=self.comment.text())
        self._after_movement('Sortie de stock', pid)

    def _record_loss(self) -> None:
        if not self._ensure_stock_permission():
            return
        pid = self._current_product_id()
        if not pid or self.quantity.value() <= 0:
            warn(self, t('Choisissez un produit et une quantité.'))
            return
        try:
            InventoryService.record_loss(pid, self.quantity.value(), self.loss_reason.currentText(), comment=self.comment.text(), user_id=self.state.user_id, username=getattr(self.state.current_user, 'username', ''))
        except ValueError as exc:
            warn(self, str(exc))
            return
        self._after_movement('Perte de stock', pid)

    def _inventory(self) -> None:
        if not self._ensure_stock_permission():
            return
        pid = self._current_product_id()
        if not pid:
            warn(self, t('Choisissez un produit.'))
            return
        StockController.set_inventory(pid, self.quantity.value(), self.reason.text().strip() or 'Inventaire', self.state.user_id, comment=self.comment.text())
        self._after_movement('Inventaire', pid)

    def _correction(self) -> None:
        if not self._ensure_stock_permission():
            return
        pid = self._current_product_id()
        if not pid:
            warn(self, t('Choisissez un produit.'))
            return
        motif = self.reason.text().strip()
        if not motif:
            warn(self, t("Indiquez un motif pour l'ajustement (ex. : correction erreur de saisie)."))
            return
        StockController.correct(pid, self.quantity.value(), motif, self.state.user_id, comment=self.comment.text())
        self._after_movement('Ajustement / correction', pid)

    def _after_movement(self, label: str, pid: int) -> None:
        audit_service.log_action(label, 'Stock', f'produit={pid}', self.state.user_id, getattr(self.state.current_user, 'username', ''))
        self.quantity.setValue(0)
        self.unit_cost.setValue(0)
        self.invoice_number.clear()
        self.reason.clear()
        self.comment.clear()
        self._reload_products()
        self._reload_history()
        self.state.notify_data_changed()
        info(self, f'{label} enregistré(e).')

    def refresh(self) -> None:
        self._reload_products()
        self._reload_suppliers()
        self._reload_history()

    def _reload_products(self, *_a) -> None:
        keep = self._current_product_id()
        text = self.product_search.text().strip().lower()
        self._products = [p for p in ProductController.list(only_active=False) if not text or text in p.name.lower()]
        self.product_table.blockSignals(True)
        self.product_table.setRowCount(len(self._products))
        for row, product in enumerate(self._products):
            tracked = not getattr(product, 'sell_without_stock', False)
            alert = (t('Rupture') if product.is_out_of_stock else (t('Bas') if product.is_low_stock else '')) if tracked else ''
            for col, value in enumerate([product.name, format_quantity(product.quantity), alert]):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, product.id)
                if col == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if col == 2 and alert:
                    item.setForeground(QColor('#b91c1c' if product.is_out_of_stock else '#b45309'))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.product_table.setItem(row, col, item)
        self.product_table.blockSignals(False)
        ids = [p.id for p in self._products]
        if ids:
            self.product_table.selectRow(ids.index(keep) if keep in ids else 0)
        self._show_product()

    def _reload_suppliers(self) -> None:
        current = self.supplier_combo.currentData()
        self.supplier_combo.blockSignals(True)
        self.supplier_combo.clear()
        self.supplier_combo.addItem(t('— Aucun —'), None)
        for supplier in SupplierController.list():
            self.supplier_combo.addItem(supplier.name, supplier.id)
        index = self.supplier_combo.findData(current)
        if index >= 0:
            self.supplier_combo.setCurrentIndex(index)
        self.supplier_combo.blockSignals(False)

    def _reload_history(self) -> None:
        movements = StockController.history(limit=self.HISTORY_LIMIT)
        kinds = sorted({m.movement_type for m in movements if m.movement_type})
        if [self.history_type.itemData(i) for i in range(1, self.history_type.count())] != kinds:
            self.history_type.blockSignals(True)
            chosen = self.history_type.currentData()
            self.history_type.clear()
            self.history_type.addItem(t('Tous les mouvements'), None)
            for k in kinds:
                self.history_type.addItem(k, k)
            self.history_type.setCurrentIndex(max(0, self.history_type.findData(chosen)))
            self.history_type.blockSignals(False)
        text = self.history_search.text().strip().lower()
        kind = self.history_type.currentData()
        movements = [m for m in movements if (not kind or m.movement_type == kind)
                     and (not text or text in (m.product.name.lower() if m.product else ''))]
        self.history_note.setText(f'Historique limité aux {self.HISTORY_LIMIT} derniers mouvements.' if len(movements) == self.HISTORY_LIMIT else '')
        self.history_table.setRowCount(len(movements))
        for row, movement in enumerate(movements):
            product_name = movement.product.name if movement.product else '—'
            signed = movement.signed_quantity
            qty_text = f'+{format_quantity(signed)}' if signed > 0 else format_quantity(signed)
            values = [format_datetime(movement.date), movement.user_label, product_name, movement.movement_type, qty_text, format_quantity(movement.quantity_after), movement.supplier_name or '—', movement.invoice_number or '—', movement.reason or '—', movement.comment or '—']
            for col, value in enumerate(values):
                self.history_table.setItem(row, col, QTableWidgetItem(value))
