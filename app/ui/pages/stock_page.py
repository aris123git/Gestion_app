"""Page de gestion du stock : entrées, sorties, inventaire, corrections, historique."""
from __future__ import annotations
from app.i18n import t
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget
from app.controllers.product_controller import ProductController
from app.controllers.stock_controller import StockController
from app.controllers.supplier_controller import SupplierController
from app.services import audit_service, permissions as perms
from app.services.inventory_service import InventoryService
from app.ui.responsive import LayoutProfile, STOCK_HISTORY_COLUMNS, TableColumnController
from app.ui.state import AppState
from app.ui.widgets.helpers import confirm, info, make_card, page_title, warn
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
        self.tabs.addTab(self._build_inventory_tab(), t('Inventaire complet'))
        self.tabs.addTab(self._build_order_tab(), t('À commander'))
        self.purchases = None
        if state.can(perms.MANAGE_PURCHASES):      # réception de marchandise : plus de page Achats séparée
            from app.ui.pages.purchases_page import PurchasesPage
            self.purchases = PurchasesPage(state, embedded=True)
            self.tabs.addTab(self.purchases, t('Achats'))
        self.tabs.addTab(self._build_history_tab(), t('Historique'))
        self.tabs.currentChanged.connect(lambda _: (self._reload_history(), self._reload_inventory(), self._refresh_purchases()))
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

    # -- inventaire complet -------------------------------------------------------------------------------------
    def _build_inventory_tab(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 12, 0, 0)
        bar = QHBoxLayout()
        self.inv_search = QLineEdit()
        self.inv_search.setPlaceholderText(t('Rechercher un produit…'))
        self.inv_search.textChanged.connect(self._reload_inventory)
        self.inv_expected = QCheckBox(t('Montrer le stock attendu sur la feuille imprimée'))
        print_btn = QPushButton(t('Imprimer la feuille'))
        print_btn.clicked.connect(self._print_inventory)
        self.inv_validate = QPushButton(t("Valider l'inventaire"))
        self.inv_validate.setObjectName('Primary')
        self.inv_validate.clicked.connect(self._validate_inventory)
        bar.addWidget(self.inv_search, 1)
        bar.addWidget(self.inv_expected)
        bar.addWidget(print_btn)
        bar.addWidget(self.inv_validate)
        layout.addLayout(bar)
        self.inv_hint = QLabel(t("Imprimez la feuille, comptez, puis saisissez ici les quantités comptées. Les produits laissés vides ne sont pas modifiés."))
        self.inv_hint.setStyleSheet('color: #64748b;')
        self.inv_hint.setWordWrap(True)
        layout.addWidget(self.inv_hint)
        self.inv_table = QTableWidget(0, 4)
        self.inv_table.setHorizontalHeaderLabels([t('Produit'), t('Stock système'), t('Compté'), t('Écart')])
        self.inv_table.verticalHeader().setVisible(False)
        self.inv_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.inv_table.itemChanged.connect(self._inventory_edited)
        layout.addWidget(self.inv_table, 1)
        self._inv_counts: dict = {}
        self._inv_loading = False
        return wrap

    # ---- Suggestion de commande -------------------------------------------------
    def _build_order_tab(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 12, 0, 0)
        bar = QHBoxLayout()
        self.order_supplier = QComboBox()
        self.order_supplier.currentIndexChanged.connect(self._reload_order)
        self.order_print = QPushButton(t('Imprimer (PDF)'))
        self.order_print.clicked.connect(self._print_order)
        self.order_wa = QPushButton(t('Envoyer par WhatsApp'))
        self.order_wa.setObjectName('Primary')
        self.order_wa.clicked.connect(self._whatsapp_order)
        bar.addWidget(QLabel(t('Fournisseur')))
        bar.addWidget(self.order_supplier, 1)
        bar.addWidget(self.order_print)
        bar.addWidget(self.order_wa)
        layout.addLayout(bar)
        hint = QLabel(t("Produits en rupture ou sous le minimum. Quantité proposée = 2 × minimum − stock ; modifiez-la ou décochez un produit."))
        hint.setStyleSheet('color: #64748b;')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.order_table = QTableWidget(0, 5)
        self.order_table.setHorizontalHeaderLabels(['', t('Produit'), t('Fournisseur'), t('Stock'), t('À commander')])
        self.order_table.verticalHeader().setVisible(False)
        self.order_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.order_table, 1)
        self._order_loading = False
        self._order_suppliers_loaded = False
        return wrap

    @staticmethod
    def suggested_quantity(product) -> float:
        stock = float(product.quantity or 0)
        minimum = float(product.min_stock or 0)
        return max(2 * minimum - stock, 1.0)

    def _order_candidates(self):
        out = []
        for p in self._inventory_products():
            stock = float(p.quantity or 0)
            minimum = float(p.min_stock or 0)
            if stock <= 0 or (minimum > 0 and stock <= minimum):
                out.append(p)
        return out

    def _reload_order(self, *_a) -> None:
        if not hasattr(self, 'order_table') or self._order_loading:
            return
        self._order_loading = True
        names = {s.id: s.name for s in SupplierController.list()}
        if not self._order_suppliers_loaded or self.order_supplier.count() != len(names) + 2:
            current = self.order_supplier.currentData()
            self.order_supplier.blockSignals(True)
            self.order_supplier.clear()
            self.order_supplier.addItem(t('Tous'), 'all')
            self.order_supplier.addItem(t('Sans fournisseur'), 'none')
            for sid, name in names.items():
                self.order_supplier.addItem(name, sid)
            idx = self.order_supplier.findData(current)
            self.order_supplier.setCurrentIndex(max(idx, 0))
            self.order_supplier.blockSignals(False)
            self._order_suppliers_loaded = True
        flt = self.order_supplier.currentData()
        products = []
        for p in self._order_candidates():
            sid = getattr(p, 'supplier_id', None)
            if flt == 'all' or (flt == 'none' and not sid) or flt == sid:
                products.append(p)
        self.order_table.setRowCount(len(products))
        for row, p in enumerate(products):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked)
            name = QTableWidgetItem(p.name)
            name.setData(Qt.ItemDataRole.UserRole, p.id)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            sup = QTableWidgetItem(names.get(getattr(p, 'supplier_id', None), '—'))
            sup.setFlags(sup.flags() & ~Qt.ItemFlag.ItemIsEditable)
            stock = QTableWidgetItem(format_quantity(p.quantity))
            stock.setFlags(stock.flags() & ~Qt.ItemFlag.ItemIsEditable)
            stock.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            qty = QTableWidgetItem(format_quantity(self.suggested_quantity(p)))
            qty.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for col, item in enumerate((chk, name, sup, stock, qty)):
                self.order_table.setItem(row, col, item)
        self._order_loading = False

    def _order_lines(self):
        """Lignes cochées : (produit, unité, stock, quantité) avec quantité > 0."""
        units = {p.id: (p.unit_name or '') for p in self._inventory_products()}
        lines = []
        for row in range(self.order_table.rowCount()):
            if self.order_table.item(row, 0).checkState() != Qt.CheckState.Checked:
                continue
            qty = self._parse_count(self.order_table.item(row, 4).text())
            if not qty:
                continue
            pid = self.order_table.item(row, 1).data(Qt.ItemDataRole.UserRole)
            lines.append((self.order_table.item(row, 1).text(), units.get(pid, ''), self.order_table.item(row, 3).text(), qty))
        return lines

    @staticmethod
    def order_text(lines) -> str:
        parts = [f"{name} × {format_quantity(qty)}" for name, _u, _s, qty in lines]
        return t("Bonjour, je voudrais commander : ") + ", ".join(parts) + "."

    def _print_order(self) -> None:
        lines = self._order_lines()
        if not lines:
            warn(self, t('À commander'), t('Aucun produit à commander.'))
            return
        import tempfile
        from pathlib import Path

        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from app.printers.order_list import build_order_list

        rows = [(n, u, s, format_quantity(q)) for n, u, s, q in lines]
        sup = self.order_supplier.currentText() if isinstance(self.order_supplier.currentData(), int) else ''
        path = Path(tempfile.gettempdir()) / 'liste_commande.pdf'
        build_order_list(rows, path, supplier=sup)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _whatsapp_order(self) -> None:
        lines = self._order_lines()
        if not lines:
            warn(self, t('À commander'), t('Aucun produit à commander.'))
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from app.services.messaging_service import whatsapp_link

        phone = ''
        sid = self.order_supplier.currentData()
        if isinstance(sid, int):
            sup = next((s for s in SupplierController.list() if s.id == sid), None)
            phone = (sup.phone if sup else '') or ''
        try:
            url = whatsapp_link(phone, self.order_text(lines)) if phone else \
                'https://wa.me/?text=' + __import__('urllib.parse', fromlist=['quote']).quote(self.order_text(lines), safe='')
        except ValueError:
            warn(self, 'WhatsApp', t('Numéro de téléphone du fournisseur invalide.'))
            return
        QDesktopServices.openUrl(QUrl(url))

    def _inventory_products(self):
        return [p for p in ProductController.list(only_active=True) if not getattr(p, 'sell_without_stock', False)]

    @staticmethod
    def _parse_count(text: str):
        text = (text or '').strip().replace(',', '.').replace(' ', '')
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
        return value if value >= 0 else None

    def _reload_inventory(self, *_a) -> None:
        if not hasattr(self, 'inv_table'):
            return
        text = self.inv_search.text().strip().lower()
        products = [p for p in self._inventory_products() if not text or text in p.name.lower()]
        self._inv_loading = True
        self.inv_table.setRowCount(len(products))
        for row, product in enumerate(products):
            name = QTableWidgetItem(product.name)
            name.setData(Qt.ItemDataRole.UserRole, product.id)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            stock = QTableWidgetItem(format_quantity(product.quantity))
            stock.setData(Qt.ItemDataRole.UserRole, float(product.quantity or 0))
            stock.setFlags(stock.flags() & ~Qt.ItemFlag.ItemIsEditable)
            stock.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            counted = QTableWidgetItem(self._inv_counts.get(product.id, ''))
            counted.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            gap = QTableWidgetItem('')
            gap.setFlags(gap.flags() & ~Qt.ItemFlag.ItemIsEditable)
            gap.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for col, item in enumerate((name, stock, counted, gap)):
                self.inv_table.setItem(row, col, item)
        self._inv_loading = False
        for row in range(self.inv_table.rowCount()):
            self._update_gap(row)

    def _update_gap(self, row: int) -> None:
        stock = self.inv_table.item(row, 1).data(Qt.ItemDataRole.UserRole)
        counted = self._parse_count(self.inv_table.item(row, 2).text())
        gap = self.inv_table.item(row, 3)
        self._inv_loading = True
        if counted is None:
            gap.setText('')
        else:
            diff = counted - stock
            gap.setText('0' if abs(diff) < 0.0005 else (f'+{format_quantity(diff)}' if diff > 0 else format_quantity(diff)))
            gap.setForeground(QColor('#0f172a' if abs(diff) < 0.0005 else ('#15803d' if diff > 0 else '#b91c1c')))
        self._inv_loading = False

    def _inventory_edited(self, item) -> None:
        if self._inv_loading or item.column() != 2:
            return
        pid = self.inv_table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)
        self._inv_counts[pid] = item.text()
        self._update_gap(item.row())

    def _print_inventory(self) -> None:
        import tempfile
        from pathlib import Path

        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from app.printers.inventory_sheet import build_inventory_sheet

        show = self.inv_expected.isChecked()
        rows = [(p.name, p.unit_name or '', format_quantity(p.quantity)) for p in self._inventory_products()]
        path = Path(tempfile.gettempdir()) / 'feuille_inventaire.pdf'
        build_inventory_sheet(rows, path, show_expected=show)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _validate_inventory(self) -> None:
        if not self._ensure_stock_permission():
            return
        products = {p.id: p for p in self._inventory_products()}
        todo = []
        for pid, text in self._inv_counts.items():
            counted = self._parse_count(text)
            product = products.get(pid)
            if counted is None or product is None:
                continue
            if abs(counted - float(product.quantity or 0)) >= 0.0005:
                todo.append((product, counted))
        entered = sum(1 for text in self._inv_counts.values() if self._parse_count(text) is not None)
        if not entered:
            warn(self, t('Saisissez au moins une quantité comptée.'))
            return
        if not todo:
            info(self, t('Aucun écart : le stock est déjà juste pour tous les produits comptés.'))
            self._inv_counts.clear()
            self._reload_inventory()
            return
        if not confirm(self, f"{len(todo)} " + t('produit(s) seront corrigés sur') + f" {entered} " + t('comptés. Valider ?')):
            return
        from datetime import date

        reason = f'Inventaire complet {date.today():%d/%m/%Y}'
        for product, counted in todo:
            StockController.set_inventory(product.id, counted, reason, self.state.user_id)
        audit_service.log_action('Inventaire complet', 'Stock', f'{len(todo)} produits corrigés', self.state.user_id, getattr(self.state.current_user, 'username', ''))
        self._inv_counts.clear()
        self._reload_products()
        self._reload_inventory()
        self._reload_history()
        self.state.notify_data_changed()
        info(self, f"{len(todo)} " + t('produit(s) corrigé(s).'))

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
        if self.unit_cost.value() <= 0 and not confirm(self, t("Coût unitaire non renseigné : le bénéfice de ces unités sera calculé au dernier prix d'achat connu. Enregistrer quand même ?")):
            return
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

    def _refresh_purchases(self) -> None:
        if self.purchases is not None and self.tabs.currentWidget() is self.purchases:
            self.purchases.refresh()

    def refresh(self) -> None:
        self._refresh_purchases()
        self._reload_inventory()
        self._reload_order()
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
