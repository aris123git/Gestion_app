"""Page de gestion des produits (liste, ajout, modification, suppression)."""
from __future__ import annotations
from app.i18n import t
from app.ui.widgets.batch import enable_multi, run_batch, selected_rows
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from app.controllers.category_controller import CategoryController
from app.controllers.product_controller import ProductController
from app.reports.excel_report import export_products_excel
from app.services import audit_service, permissions as perms, product_profile, settings_service
from app.ui.dialogs.product_dialog import ProductDialog
from app.ui.responsive import LayoutProfile
from app.ui.state import AppState
from app.ui.widgets.helpers import confirm, info, make_card, page_title, warn
from app.utils.helpers import format_money, format_quantity

class ProductsPage(QWidget):
    HEADERS = ['Nom', 'Catégorie', 'Prix vente', 'Stock', 'Alerte']
    LIST_LIMIT = 5000

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._maquis = product_profile.is_maquis()
        self._ids: list[int] = []
        self._rows: list = []
        self._stock_filter = None          # None | 'low' | 'out'
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(page_title(t('Produits')))
        header.addStretch()
        self.more_button = QPushButton(t('Plus'))
        menu = QMenu(self.more_button)
        self.categories_button = menu.addAction(t('Catégories et unités'))
        self.categories_button.triggered.connect(self._open_categories)
        self.export_button = menu.addAction(t('Exporter Excel'))
        self.export_button.triggered.connect(self._export)
        self.more_button.setMenu(menu)
        self.add_button = QPushButton(t('+ Nouveau produit'))
        self.add_button.setObjectName('Primary')
        self.add_button.clicked.connect(self._add)
        header.addWidget(self.more_button)
        header.addWidget(self.add_button)
        layout.addLayout(header)
        kp = QHBoxLayout()
        self.k_all, self.k_low, self.k_out, self.k_value = QLabel(), QLabel(), QLabel(), QLabel()
        self._kpi_cards = []
        for k in (self.k_all, self.k_low, self.k_out, self.k_value):
            k.setTextFormat(Qt.TextFormat.RichText)
            card = make_card(k)
            self._kpi_cards.append(card)
            kp.addWidget(card, 1)
        layout.addLayout(kp)
        self._catalog_hint = QLabel('')
        self._catalog_hint.setWordWrap(True)
        self._catalog_hint.setStyleSheet('color: #1d4ed8; font-size: 12px;')
        layout.addWidget(self._catalog_hint)
        self._refresh_catalog_hint()
        filters = QHBoxLayout()
        self.search = QLineEdit()
        placeholder = (
            t('Rechercher (nom)…')
            if self._maquis
            else t('Rechercher (nom, code-barres, référence)…')
        )
        self.search.setPlaceholderText(placeholder)
        self.search.textChanged.connect(self.refresh)
        filters.addWidget(self.search, 1)
        self._chips = {}
        for key, label in ((None, 'Tous'), ('low', 'Stock bas'), ('out', 'En rupture')):
            b = QPushButton(t(label))
            b.setCheckable(True)
            b.setStyleSheet('QPushButton:checked { background: #2563eb; color: #ffffff; border-color: #2563eb; }')
            b.clicked.connect(lambda _=False, k=key: self._set_stock_filter(k))
            self._chips[key] = b
            filters.addWidget(b)
        self.category_filter = QComboBox()
        self.category_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.category_filter)
        layout.addLayout(filters)
        self.limit_note = QLabel('')
        self.limit_note.setStyleSheet('color: #b45309; font-size: 12px;')
        self.limit_note.setWordWrap(True)
        layout.addWidget(self.limit_note)
        body = QHBoxLayout()
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels([t(h) for h in self.HEADERS])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        enable_multi(self.table)
        self.table.doubleClicked.connect(self._edit)
        self.table.currentCellChanged.connect(lambda *_: self._show_detail())
        body.addWidget(self.table, 3)
        side = QVBoxLayout()
        self.d_head = QLabel(t('Sélectionnez un produit.'))
        self.d_head.setTextFormat(Qt.TextFormat.RichText)
        self.d_head.setWordWrap(True)
        side.addWidget(self.d_head)
        self.d_info = QLabel()
        self.d_info.setTextFormat(Qt.TextFormat.RichText)
        self.d_info.setWordWrap(True)
        self.d_info.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.d_info.setMinimumHeight(140)
        side.addWidget(make_card(self.d_info))
        self.edit_button = QPushButton(t('Modifier'))
        self.edit_button.setObjectName('Primary')
        self.edit_button.clicked.connect(self._edit)
        self.delete_button = QPushButton(t('Supprimer'))
        self.delete_button.setObjectName('DangerOutline')
        self.delete_button.clicked.connect(self._delete)
        actions = QHBoxLayout()
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        side.addLayout(actions)
        side.addStretch()
        body.addLayout(side, 2)
        layout.addLayout(body, 1)
        self._apply_permissions()
        self.state.layout_changed.connect(self._on_layout_changed)
        if self.state.layout is not None:
            self._on_layout_changed(self.state.layout)

    def _on_layout_changed(self, profile: LayoutProfile) -> None:
        margins = 12 if profile.density == 'compact' else 24
        self.layout().setContentsMargins(margins, margins, margins, margins)

    def _can_see_costs(self) -> bool:
        return self.state.can(perms.VIEW_PROFITS) or self.state.can(perms.MANAGE_PRODUCTS)

    def _apply_permissions(self) -> None:
        can_manage = self.state.can(perms.MANAGE_PRODUCTS)
        can_delete = self.state.can(perms.DELETE_PRODUCTS)
        self.add_button.setVisible(can_manage)
        self.edit_button.setVisible(can_manage)
        self.delete_button.setVisible(can_delete)
        self.export_button.setVisible(self._can_see_costs())
        self.categories_button.setVisible(self.state.can(perms.MANAGE_CATEGORIES) and not product_profile.is_maquis())
        self.more_button.setVisible(self.export_button.isVisible() or self.categories_button.isVisible())

    def _set_stock_filter(self, key) -> None:
        self._stock_filter = key
        self.refresh()

    def _refresh_catalog_hint(self) -> None:
        from app.services import catalog_features

        bits = []
        if catalog_features.product_images_enabled():
            bits.append(t('product.upload_enabled_hint'))
        if catalog_features.category_browser_enabled():
            bits.append(t('product.add_category_tip'))
        self._catalog_hint.setText(' '.join(bits))
        self._catalog_hint.setVisible(bool(bits))

    @staticmethod
    def _tracked(product) -> bool:
        return not getattr(product, 'sell_without_stock', False)

    def refresh(self) -> None:
        self._apply_permissions()
        self._refresh_catalog_hint()
        self._reload_categories()
        for k, b in self._chips.items():
            b.setChecked(k == self._stock_filter)
        keep = self._selected_id()
        products = ProductController.list(search=self.search.text().strip(), category_id=self.category_filter.currentData(), limit=self.LIST_LIMIT)
        self.limit_note.setText(f"Affichage limité aux {self.LIST_LIMIT} premiers produits. Affinez la recherche ou la catégorie si le produit recherché n'apparaît pas." if len(products) == self.LIST_LIMIT else '')
        self.limit_note.setVisible(bool(self.limit_note.text()))
        currency = settings_service.get_currency()
        allp = ProductController.list(limit=self.LIST_LIMIT)
        tracked = [p for p in allp if self._tracked(p)]
        low = [p for p in tracked if p.is_low_stock and not p.is_out_of_stock]
        out = [p for p in tracked if p.is_out_of_stock]
        grey = "<span style='color:#64748b'>%s</span><br><b style='font-size:22px'>%s</b>"
        self.k_all.setText(grey % (t('Produits'), len(allp)))
        self.k_low.setText(grey % (t('Stock bas'), len(low)))
        self.k_out.setText(grey % (t('En rupture'), len(out)))
        value = sum(float(p.quantity or 0) * float(p.purchase_price or 0) for p in tracked)
        self.k_value.setText(grey % (t("Valeur du stock (achat)"), format_money(value, currency)))
        self._kpi_cards[3].setVisible(self._can_see_costs())
        if self._stock_filter == 'low':
            products = [p for p in products if self._tracked(p) and p.is_low_stock and not p.is_out_of_stock]
        elif self._stock_filter == 'out':
            products = [p for p in products if self._tracked(p) and p.is_out_of_stock]
        self._rows = list(products)
        self._ids = [p.id for p in products]
        self.table.blockSignals(True)
        self.table.setRowCount(len(products))
        for row, product in enumerate(products):
            name = product.name
            if getattr(product, 'free_amount_sale', False):
                name = f'{product.name} · montant libre'
            if getattr(product, 'free_amount_sale', False):
                price_txt = f'réf. {format_money(product.sale_price, currency)}/kg'
            else:
                price_txt = format_money(product.sale_price, currency)
            if not self._tracked(product):
                stock_txt, alert = t('Sans stock'), ''
            else:
                stock_txt = f"{format_quantity(product.quantity)} {product.unit_name or ''}".strip()
                alert = t('Rupture') if product.is_out_of_stock else (t('Bas') if product.is_low_stock else '')
            cells = [name, product.category_name or '—', price_txt, stock_txt, alert]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col in (2, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if col == 4 and alert:
                    item.setForeground(QColor('#b91c1c' if product.is_out_of_stock else '#b45309'))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        if self._rows:
            target = self._ids.index(keep) if keep in self._ids else 0
            self.table.selectRow(target)
        self._show_detail()

    def _show_detail(self) -> None:
        pid = self._selected_id()
        product = next((p for p in self._rows if p.id == pid), None)
        has = product is not None
        self.edit_button.setEnabled(has)
        self.delete_button.setEnabled(has)
        if not has:
            self.d_head.setText(t('Sélectionnez un produit.'))
            self.d_info.setText('')
            return
        currency = settings_service.get_currency()
        barcode = product.barcode or ''
        sub = f"{t('Code-barres')} {barcode}" if barcode and not self._maquis else (product.category_name or '')
        self.d_head.setText(f"<b style='font-size:15px'>{product.name}</b><br><span style='color:#64748b'>{sub}</span>")
        sale, cost = float(product.sale_price or 0), float(product.purchase_price or 0)
        lines = [(t('Prix de vente'), f'<b>{format_money(sale, currency)}</b>')]
        if self._can_see_costs():
            lines.append((t("Prix d'achat"), format_money(cost, currency)))
            if sale > 0:
                lines.append((t('Marge'), f'{format_money(sale - cost, currency)} ({(sale - cost) / sale * 100:.0f} %)'))
        if self._tracked(product):
            qty = f"{format_quantity(product.quantity)} {product.unit_name or ''}".strip()
            color = '#b91c1c' if product.is_out_of_stock or product.is_low_stock else '#0f172a'
            flag = f" ({t('rupture')})" if product.is_out_of_stock else (f" ({t('bas')})" if product.is_low_stock else '')
            lines.append((t('Stock'), f"<b style='color:{color}'>{qty}{flag}</b>"))
        else:
            lines.append((t('Stock'), t('Sans stock')))
        self.d_info.setText('<table width="100%" cellspacing="6">' + ''.join(
            f"<tr><td>{a}</td><td align='right'>{b}</td></tr>" for a, b in lines) + '</table>')

    def _reload_categories(self) -> None:
        current = self.category_filter.currentData()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem(t('Toutes'), None)
        for category in CategoryController.list():
            self.category_filter.addItem(category.name, category.id)
        index = self.category_filter.findData(current)
        if index >= 0:
            self.category_filter.setCurrentIndex(index)
        self.category_filter.blockSignals(False)

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            return None
        return self._ids[row]

    def select_product(self, product_id: int) -> None:
        if product_id not in self._ids:
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.category_filter.setCurrentIndex(0)
            self.refresh()
        if product_id in self._ids:
            row = self._ids.index(product_id)
            self.table.selectRow(row)
            item = self.table.item(row, 0)
            if item:
                self.table.scrollToItem(item)

    def _add(self) -> None:
        if not self.state.can(perms.MANAGE_PRODUCTS):
            warn(self, t("Vous n'avez pas l'autorisation d'ajouter un produit."))
            return
        dialog = ProductDialog(parent=self)
        if dialog.exec() and dialog.data:
            product = ProductController.create(dialog.data)
            audit_service.log_action('Création produit', 'Product', product.name, self.state.user_id, getattr(self.state.current_user, 'username', ''))
            self.refresh()
            self.state.notify_data_changed()

    def _edit(self) -> None:
        if not self.state.can(perms.MANAGE_PRODUCTS):
            return
        product_id = self._selected_id()
        if not product_id:
            warn(self, t('Veuillez sélectionner un produit.'))
            return
        product = ProductController.get(product_id)
        dialog = ProductDialog(product=product, parent=self)
        if dialog.exec() and dialog.data:
            data = dict(dialog.data)
            if not self._ask_price_timing(product, data):
                return
            ProductController.update(product_id, data)
            audit_service.log_action('Modification produit', 'Product', dialog.data['name'], self.state.user_id, getattr(self.state.current_user, 'username', ''))
            self.refresh()
            self.state.notify_data_changed()

    def _ask_price_timing(self, product, data: dict) -> bool:
        """Si les prix changent alors qu'il reste du stock : maintenant ou après son écoulement ? False = annulé."""
        from PySide6.QtWidgets import QMessageBox

        changed = (abs(float(data.get('sale_price') or 0) - float(product.sale_price or 0)) >= 0.001
                   or abs(float(data.get('purchase_price') or 0) - float(product.purchase_price or 0)) >= 0.001)
        stock = float(product.quantity or 0)
        if not changed or stock <= 0 or getattr(product, 'sell_without_stock', False):
            return True
        box = QMessageBox(self)
        box.setWindowTitle(t('Changement de prix'))
        box.setText(t("Il reste {n:g} en stock au prix actuel. Quand appliquer le nouveau prix ?").format(n=stock))
        later = box.addButton(t('Après épuisement du stock actuel'), QMessageBox.ButtonRole.AcceptRole)
        now = box.addButton(t('Maintenant'), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(t('Annuler'), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is later:
            data['price_timing'] = 'after_stock'
            return True
        return clicked is now

    def _delete_many(self, rows: list[int]) -> None:
        if not self.state.can(perms.DELETE_PRODUCTS):
            warn(self, t("Vous n'avez pas l'autorisation de supprimer un produit."))
            return
        user = getattr(self.state.current_user, 'username', '')

        def one(pid: int) -> None:
            ProductController.delete(pid)
            audit_service.log_action('Suppression produit', 'Product', str(pid), self.state.user_id, user)

        items = [(self._ids[r], self.table.item(r, 0).text()) for r in rows]
        if run_batch(self, t("Supprimer {n} produits ?\n\nCeux qui existent dans des ventes seront simplement désactivés."), items, one, t("produit(s) supprimé(s) ou désactivé(s)")):
            self.refresh()
            self.state.notify_data_changed()

    def _delete(self) -> None:
        rows = selected_rows(self.table)
        if len(rows) > 1:
            return self._delete_many(rows)
        product_id = self._selected_id()
        if not product_id:
            warn(self, t('Veuillez sélectionner un produit.'))
            return
        if not self.state.can(perms.DELETE_PRODUCTS):
            warn(self, t("Vous n'avez pas l'autorisation de supprimer un produit."))
            return
        if confirm(self, t("Supprimer ce produit ?\n\nS'il existe dans des ventes, il sera simplement désactivé pour conserver l'historique.")):
            result = ProductController.delete(product_id)
            audit_service.log_action('Suppression produit', 'Product', str(product_id), self.state.user_id, getattr(self.state.current_user, 'username', ''))
            self.refresh()
            self.state.notify_data_changed()
            if result == 'deactivated':
                info(self, t("Produit désactivé : il n'apparaît plus en caisse."))

    def _open_categories(self) -> None:
        """Catégories et unités : ouvertes ici (plus d'entrée dans le menu)."""
        from PySide6.QtWidgets import QDialog
        from app.ui.pages.categories_page import CategoriesPage
        from app.ui.widgets.dialog_fit import fit_dialog_to_screen

        dialog = QDialog(self)
        dialog.setWindowTitle(t('Catégories et unités'))
        box = QVBoxLayout(dialog)
        page = CategoriesPage(self.state)
        box.addWidget(page)
        page.refresh()
        try:
            fit_dialog_to_screen(dialog, 900, 640)
        except Exception:
            dialog.resize(900, 640)
        dialog.exec()
        self.refresh()

    def _export(self) -> None:
        products = ProductController.list(only_active=False, limit=100000)
        path = export_products_excel(products)
        info(self, f'Export réalisé :\n{path}')
