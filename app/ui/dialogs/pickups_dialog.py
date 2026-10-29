"""Enlèvements : bon d'enlèvement fournisseur, livraisons aux stations, clôture et écarts.

Réservé au type de commerce « Entreprise » (ouvert depuis la page Achats).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from app import config
from app.controllers.product_controller import ProductController
from app.controllers.sale_controller import BelowMinPriceError, CartLine, InsufficientStockError, PaymentLine, SaleController
from app.controllers.supplier_controller import SupplierController
from app.i18n import t
from app.models.pickup import STATUS_CLOSED, STATUS_DRAFT, STATUS_LABELS, STATUS_SENT, STATUS_VALIDATED
from app.services import audit_service, pickup_service as ps, settings_service
from app.ui.widgets.client_search import ClientSearchField
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import confirm, info, warn
from app.ui.widgets.money_spin import MoneySpinBox
from app.utils.helpers import format_datetime, format_money


def _user(state) -> tuple:
    return state.user_id, getattr(state.current_user, "username", "")


# ---------------------------------------------------------------------------
class PickupEditDialog(QDialog):
    """Création / modification d'un enlèvement (fournisseur, produits, quantités, prix d'achat)."""

    def __init__(self, parent=None, pickup_id: int | None = None):
        super().__init__(parent)
        self.setWindowTitle(t("Bon d'enlèvement"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=560, min_height=420, preferred_width=760, preferred_height=520)
        self.lines: list[ps.PickupLine] = []
        self.supplier_id = None
        self.note_text = ""
        self._products = ProductController.list()
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.supplier = QComboBox()
        self.supplier.addItem(t('— Choisir le fournisseur —'), None)
        for s in SupplierController.list():
            self.supplier.addItem(s.name, s.id)
        self.note = QLineEdit()
        self.note.setPlaceholderText(t('Camion, chauffeur, référence du fournisseur…'))
        form.addRow(t('Fournisseur (qui signe le bon)'), self.supplier)
        form.addRow(t('Note'), self.note)
        layout.addLayout(form)
        self.use_catalog_cost = QCheckBox(t("Utiliser le prix d'achat du produit"))
        self.use_catalog_cost.setChecked(True)
        self.use_catalog_cost.toggled.connect(self._cost_mode_changed)
        layout.addWidget(self.use_catalog_cost)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([t('Produit'), t('Quantité'), t("Prix d'achat"), t('Total')])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        add = QPushButton(t('Ajouter un produit'))
        add.clicked.connect(lambda: self._add_row())
        remove = QPushButton(t('Retirer la ligne'))
        remove.clicked.connect(self._remove_row)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        self.total_label = QLabel('')
        row.addWidget(self.total_label)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if pickup_id:
            self._load(pickup_id)
        else:
            self._add_row()

    # -- lignes --------------------------------------------------------
    def _add_row(self, product_id=None, qty=0.0, cost=0.0) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        combo = QComboBox()
        for p in self._products:
            combo.addItem(p.name, p.id)
        if product_id is not None:
            combo.setCurrentIndex(max(0, combo.findData(product_id)))
        qty_spin = QDoubleSpinBox()
        qty_spin.setRange(0, 1_000_000_000)
        qty_spin.setDecimals(3)
        qty_spin.setValue(qty)
        cost_spin = MoneySpinBox()
        cost_spin.setRange(0, 1_000_000_000)
        cost_spin.setValue(cost)
        for w in (combo, qty_spin, cost_spin):
            self.table.setCellWidget(r, {combo: 0, qty_spin: 1, cost_spin: 2}[w], w)
        self.table.setItem(r, 3, QTableWidgetItem(''))
        combo.currentIndexChanged.connect(lambda _=0, row=r: self._product_changed(row))
        qty_spin.valueChanged.connect(self._recalc)
        cost_spin.valueChanged.connect(self._recalc)
        self._product_changed(r)

    def _catalog_cost(self, product_id) -> float:
        for p in self._products:
            if p.id == product_id:
                return float(p.purchase_price or 0)
        return 0.0

    def _product_changed(self, row: int) -> None:
        combo, cost = self.table.cellWidget(row, 0), self.table.cellWidget(row, 2)
        if self.use_catalog_cost.isChecked() and combo is not None:
            cost.setValue(self._catalog_cost(combo.currentData()))
        self._recalc()

    def _cost_mode_changed(self, checked: bool) -> None:
        for r in range(self.table.rowCount()):
            self.table.cellWidget(r, 2).setEnabled(not checked)
            if checked:
                self._product_changed(r)

    def _remove_row(self) -> None:
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self._recalc()

    def _recalc(self) -> None:
        total = 0.0
        for r in range(self.table.rowCount()):
            q, c = self.table.cellWidget(r, 1).value(), self.table.cellWidget(r, 2).value()
            self.table.cellWidget(r, 2).setEnabled(not self.use_catalog_cost.isChecked())
            self.table.item(r, 3).setText(format_money(q * c, settings_service.get_currency()))
            total += q * c
        self.total_label.setText(f"<b>{t('Total')} : {format_money(total, settings_service.get_currency())}</b>")

    def _load(self, pickup_id: int) -> None:
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        from app.database.connection import session_scope
        from app.models.pickup import Pickup

        with session_scope() as s:
            pk = s.execute(select(Pickup).options(joinedload(Pickup.items)).where(Pickup.id == pickup_id)).unique().scalar_one()
            self.supplier.setCurrentIndex(max(0, self.supplier.findData(pk.supplier_id)))
            self.note.setText(pk.note or '')
            items = [(i.product_id, float(i.quantity), float(i.unit_cost)) for i in pk.items]
        self.use_catalog_cost.setChecked(False)
        for pid, q, c in items:
            self._add_row(pid, q, c)
        self._cost_mode_changed(False)

    def _accept(self) -> None:
        lines = []
        for r in range(self.table.rowCount()):
            pid = self.table.cellWidget(r, 0).currentData()
            q, c = self.table.cellWidget(r, 1).value(), self.table.cellWidget(r, 2).value()
            if pid and q > 0:
                lines.append(ps.PickupLine(pid, q, c))
        if not lines:
            warn(self, t('Ajoutez au moins un produit avec une quantité.'))
            return
        self.lines, self.supplier_id, self.note_text = lines, self.supplier.currentData(), self.note.text()
        self.accept()


# ---------------------------------------------------------------------------
class ValidatePickupDialog(QDialog):
    """Validation : le fournisseur a signé le bon ; le stock entre par un achat."""

    def __init__(self, parent=None, total: float = 0.0):
        super().__init__(parent)
        self.setWindowTitle(t("Valider l'enlèvement"))
        self.setModal(True)
        self.signed_file = ''
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(t("Le fournisseur a signé et validé le bon. Le stock va entrer par un achat de {total}.").format(total=format_money(total, settings_service.get_currency()))))
        form = QFormLayout()
        self.paid = MoneySpinBox()
        self.paid.setRange(0, 1_000_000_000)
        self.paid.setToolTip(t("0 = à crédit : une dette fournisseur est créée pour le total."))
        form.addRow(t('Montant déjà payé au fournisseur'), self.paid)
        row = QHBoxLayout()
        self.file_label = QLabel(t('(aucun scan joint)'))
        pick = QPushButton(t('Joindre le bon signé…'))
        pick.clicked.connect(self._pick)
        row.addWidget(pick)
        row.addWidget(self.file_label, 1)
        form.addRow(t('Bon signé (scan / photo)'), row)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t('Bon signé'), '', 'Images et PDF (*.png *.jpg *.jpeg *.pdf)')
        if path:
            self.signed_file = path
            self.file_label.setText(Path(path).name)


# ---------------------------------------------------------------------------
class DeliverDialog(QDialog):
    """Livraison d'une partie de l'enlèvement à une station : crée la vente rattachée à l'enlèvement."""

    def __init__(self, state, pickup_id: int, parent=None):
        super().__init__(parent)
        self.state, self.pickup_id = state, pickup_id
        self.sale_id: int | None = None
        self.setWindowTitle(t('Livrer à une station'))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=560, min_height=380, preferred_width=760, preferred_height=480)
        layout = QVBoxLayout(self)
        self.client = ClientSearchField(placeholder=t('Station (nom ou téléphone)…'))
        layout.addWidget(QLabel(t('Station livrée')))
        layout.addWidget(self.client)
        self.rows = [r for r in ps.remaining(pickup_id) if r.left > 0]
        self.table = QTableWidget(len(self.rows), 4)
        self.table.setHorizontalHeaderLabels([t('Produit'), t('Reste à livrer'), t('Quantité livrée'), t('Prix de vente')])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for i, r in enumerate(self.rows):
            self.table.setItem(i, 0, QTableWidgetItem(r.name))
            self.table.setItem(i, 1, QTableWidgetItem(f'{r.left:g}'))
            q = QDoubleSpinBox()
            q.setRange(0, r.left)
            q.setDecimals(3)
            q.setValue(r.left)
            price = MoneySpinBox()
            price.setRange(0, 1_000_000_000)
            product = ProductController.get(r.product_id)
            price.setValue(float(product.sale_price or 0) if product else 0)
            q.valueChanged.connect(self._recalc)
            price.valueChanged.connect(self._recalc)
            self.table.setCellWidget(i, 2, q)
            self.table.setCellWidget(i, 3, price)
        layout.addWidget(self.table)
        form = QFormLayout()
        self.method = QComboBox()
        for m in config.PAYMENT_METHODS:
            self.method.addItem(m, m)
        self.method.addItem(t('À crédit (dette de la station)'), config.PAYMENT_METHOD_CREDIT)
        form.addRow(t('Règlement'), self.method)
        layout.addLayout(form)
        self.total_label = QLabel('')
        layout.addWidget(self.total_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t('Livrer et facturer'))
        buttons.accepted.connect(self._deliver)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._recalc()

    def _lines(self):
        out = []
        for i, r in enumerate(self.rows):
            q, p = self.table.cellWidget(i, 2).value(), self.table.cellWidget(i, 3).value()
            if q > 0:
                out.append((r, q, p))
        return out

    def _recalc(self) -> None:
        total = sum(q * p for _, q, p in self._lines())
        self.total_label.setText(f"<b>{t('Total')} : {format_money(total, settings_service.get_currency())}</b>")

    def _deliver(self) -> None:
        lines = self._lines()
        client_id = self.client.client_id
        if not client_id:
            warn(self, t('Choisissez la station (client) livrée.'))
            return
        if not lines:
            warn(self, t('Indiquez une quantité à livrer.'))
            return
        total = round(sum(q * p for _, q, p in lines), 2)
        method = self.method.currentData()
        credit = method == config.PAYMENT_METHOD_CREDIT
        user_id, username = _user(self.state)
        try:
            result = SaleController.create_sale(
                [CartLine(r.product_id, r.name, p, q) for r, q, p in lines],
                [PaymentLine(method, total)], amount_received=0 if credit else total, client_id=client_id, user_id=user_id,
                allow_credit=credit, pickup_links=[(r.item_id, q) for r, q, _ in lines],
            )
        except (ValueError, InsufficientStockError, BelowMinPriceError) as exc:
            warn(self, str(exc), t('Livraison impossible'))
            return
        audit_service.log_action('Livraison enlèvement', 'Sale', f'{result.ticket_number} pickup={self.pickup_id} total={result.total}', user_id, username)
        self.sale_id = result.sale_id
        self.ticket_number = result.ticket_number
        self.accept()


# ---------------------------------------------------------------------------
class ClosePickupDialog(QDialog):
    def __init__(self, parent=None, rows=None):
        super().__init__(parent)
        self.setWindowTitle(t("Clôturer l'enlèvement"))
        self.setModal(True)
        layout = QVBoxLayout(self)
        left = [r for r in (rows or []) if r.left > 0]
        if left:
            text = t("Le reste non livré devient une perte (sortie de stock + charge comptable) :") + "<br>" + "<br>".join(
                f"• {r.name} : <b>{r.left:g}</b> ({r.left / r.picked * 100:.2f} %)" for r in left)
        else:
            text = t("Tout a été livré : aucune perte.")
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        form = QFormLayout()
        self.reason = QComboBox()
        self.reason.addItems(ps.LOSS_REASONS)
        form.addRow(t('Motif de l’écart'), self.reason)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


# ---------------------------------------------------------------------------
class PickupsDialog(QDialog):
    """Liste des enlèvements et actions : bon, envoi, validation, livraison, clôture, détails."""

    COLS = ['N°', 'Date', 'Fournisseur', 'État', 'Enlevé', 'Livré', 'Reste', 'Écart %', 'Total']

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle(t('Enlèvements'))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=760, min_height=480, preferred_width=1100, preferred_height=640)
        self._rows: list[ps.PickupRow] = []
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(t('Rechercher (n°, fournisseur)…'))
        self.search.textChanged.connect(self._reload)
        top.addWidget(self.search, 1)
        self.show_prices = QCheckBox(t('Afficher les prix sur le bon'))
        self.show_prices.setChecked(settings_service.get_setting('bon_show_prices', '1') == '1')
        self.show_prices.toggled.connect(lambda v: settings_service.set_setting('bon_show_prices', '1' if v else '0'))
        top.addWidget(self.show_prices)
        layout.addLayout(top)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([t(c) for c in self.COLS])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.doubleClicked.connect(lambda *_: self._details())
        layout.addWidget(self.table, 1)
        self.hint = QLabel('')
        self.hint.setStyleSheet('color: #64748b;')
        layout.addWidget(self.hint)
        row1, row2 = QHBoxLayout(), QHBoxLayout()
        self.btn = {}
        for key, label, handler, layout_row in (
            ('new', 'Nouveau bon', self._new, row1), ('edit', 'Modifier', self._edit, row1), ('print', 'Imprimer le bon', self._print, row1),
            ('send', 'Marquer envoyé', self._send, row1), ('validate', 'Valider (signé)', self._validate, row1), ('delete', 'Supprimer', self._delete, row1),
            ('deliver', 'Livrer à une station', self._deliver, row2), ('close', "Clôturer (écart)", self._close, row2), ('details', 'Détails', self._details, row2),
            ('signed', 'Voir le bon signé', self._open_signed, row2), ('report', 'Rapport des écarts', self._loss_report, row2),
        ):
            b = QPushButton(t(label))
            b.clicked.connect(handler)
            layout_row.addWidget(b)
            self.btn[key] = b
        self.btn['deliver'].setObjectName('Primary')
        row2.addStretch()
        close = QPushButton(t('Fermer'))
        close.clicked.connect(self.accept)
        row2.addWidget(close)
        layout.addLayout(row1)
        layout.addLayout(row2)
        self._reload()

    # -- liste -----------------------------------------------------------
    def _selected(self):
        r = self.table.currentRow()
        return self._rows[r] if 0 <= r < len(self._rows) else None

    def _reload(self, *_args) -> None:
        keep = self._selected().id if self._selected() else None
        self._rows = ps.list_pickups(self.search.text().strip())
        self.table.setRowCount(len(self._rows))
        for i, p in enumerate(self._rows):
            cells = [p.number, format_datetime(p.date), p.supplier, STATUS_LABELS.get(p.status, p.status), f'{p.picked:g}', f'{p.delivered:g}', f'{p.left:g}',
                     f'{p.loss_percent:.2f} %' if p.status == STATUS_CLOSED else '', format_money(p.total, settings_service.get_currency())]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c >= 4:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if p.status == STATUS_CLOSED and p.loss_alert and c == 7:
                    item.setForeground(QColor('#dc2626'))
                self.table.setItem(i, c, item)
            if p.id == keep:
                self.table.selectRow(i)
        self._update_buttons()

    def _update_buttons(self) -> None:
        p = self._selected()
        st = p.status if p else None
        can = {
            'edit': st in (STATUS_DRAFT, STATUS_SENT), 'delete': st in (STATUS_DRAFT, STATUS_SENT), 'send': st == STATUS_DRAFT,
            'validate': st in (STATUS_DRAFT, STATUS_SENT), 'deliver': st == STATUS_VALIDATED and p is not None and p.left > 0,
            'close': st == STATUS_VALIDATED, 'print': p is not None, 'details': p is not None, 'signed': False, 'report': True,
        }
        if p:
            from app.database.connection import session_scope
            from app.models.pickup import Pickup
            with session_scope() as s:
                can['signed'] = bool(s.get(Pickup, p.id).signed_file)
        for key, ok in can.items():
            self.btn[key].setEnabled(bool(ok))
        self.hint.setText({
            STATUS_DRAFT: t("Brouillon : imprimez le bon, envoyez-le au fournisseur, puis validez-le une fois signé."),
            STATUS_SENT: t("Envoyé : en attente de la signature du fournisseur."),
            STATUS_VALIDATED: t("Validé : le stock est entré. Livrez aux stations ; clôturez quand c'est terminé pour enregistrer l'écart."),
            STATUS_CLOSED: t("Clôturé : le reste non livré a été enregistré comme perte."),
        }.get(st, t('Sélectionnez un enlèvement ou créez-en un.')))

    # -- actions ---------------------------------------------------------
    def _new(self) -> None:
        dlg = PickupEditDialog(self)
        if dlg.exec():
            try:
                ps.create(dlg.lines, supplier_id=dlg.supplier_id, note=dlg.note_text, user_id=self.state.user_id)
            except ValueError as exc:
                warn(self, str(exc))
            self._reload()

    def _edit(self) -> None:
        p = self._selected()
        if not p:
            return
        dlg = PickupEditDialog(self, p.id)
        if dlg.exec():
            try:
                ps.update_draft(p.id, dlg.lines, supplier_id=dlg.supplier_id, note=dlg.note_text)
            except ValueError as exc:
                warn(self, str(exc))
            self._reload()

    def _print(self) -> None:
        p = self._selected()
        if not p:
            return
        from app.printers import bon_enlevement
        try:
            path = bon_enlevement.build_pickup_bon(p.id, show_prices=self.show_prices.isChecked())
        except Exception as exc:  # noqa: BLE001 — message clair pour l'utilisateur
            warn(self, f"Impossible de générer le bon : {exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _send(self) -> None:
        p = self._selected()
        if p:
            try:
                ps.mark_sent(p.id)
            except ValueError as exc:
                warn(self, str(exc))
            self._reload()

    def _validate(self) -> None:
        p = self._selected()
        if not p:
            return
        dlg = ValidatePickupDialog(self, p.total)
        if not dlg.exec():
            return
        user_id, username = _user(self.state)
        try:
            ps.validate(p.id, amount_paid=dlg.paid.value(), signed_file=dlg.signed_file, user_id=user_id, username=username)
        except ValueError as exc:
            warn(self, str(exc), t('Validation impossible'))
        else:
            self.state.notify_data_changed()
            info(self, t("Enlèvement validé : le stock est entré."), t('Enlèvements'))
        self._reload()

    def _delete(self) -> None:
        p = self._selected()
        if p and confirm(self, t('Supprimer ce bon non validé ?')):
            try:
                ps.delete_draft(p.id)
            except ValueError as exc:
                warn(self, str(exc))
            self._reload()

    def _deliver(self) -> None:
        p = self._selected()
        if not p:
            return
        dlg = DeliverDialog(self.state, p.id, self)
        if dlg.exec() and dlg.sale_id:
            self.state.notify_data_changed()
            sale = SaleController.get(dlg.sale_id)
            if sale:
                from app.ui.dialogs.ticket_dialog import TicketDialog
                TicketDialog(sale, self, auto_print=False, message=f'Livraison enregistrée : {dlg.ticket_number}\n' + t('Entrée : imprimer · Entrée de nouveau : fermer')).exec()
        self._reload()

    def _close(self) -> None:
        p = self._selected()
        if not p:
            return
        rows = ps.remaining(p.id)
        dlg = ClosePickupDialog(self, rows)
        if dlg.exec():
            user_id, username = _user(self.state)
            try:
                lost = ps.close(p.id, dlg.reason.currentText(), user_id=user_id, username=username)
            except ValueError as exc:
                warn(self, str(exc))
            else:
                self.state.notify_data_changed()
                info(self, t("Enlèvement clôturé. Perte enregistrée : {v}").format(v=format_money(lost, settings_service.get_currency())), t('Enlèvements'))
            self._reload()

    def _details(self) -> None:
        p = self._selected()
        if not p:
            return
        lines = [f"<b>{r.name}</b> : enlevé {r.picked:g}, livré {r.delivered:g}, perte {r.loss:g}, reste {r.left:g}" for r in ps.remaining(p.id)]
        deliveries = [f"• {t_} — {c or '—'} — {n} ×{q:g}" + (' (annulée)' if s != 'completed' else '') for t_, _d, c, n, q, s in ps.delivered_sales(p.id)]
        info(self, '<br>'.join(lines + ['', f"<b>{t('Livraisons')} :</b>"] + (deliveries or [t('aucune')])), f"{t('Enlèvement')} {p.number}")

    def _loss_report(self) -> None:
        from datetime import date, timedelta
        rows = ps.loss_report(date.today() - timedelta(days=365), date.today())
        if not rows:
            info(self, t("Aucun enlèvement clôturé sur les 12 derniers mois."), t('Rapport des écarts'))
            return
        cur = settings_service.get_currency()
        lines = [f"<b>{n}</b> : enlevé {a:g}, perdu {b:g} ({pc:.2f} %), valeur {format_money(v, cur)}" for n, a, b, pc, v in rows]
        info(self, '<br>'.join(lines), t('Écarts sur 12 mois (enlèvements clôturés)'))

    def _open_signed(self) -> None:
        p = self._selected()
        if not p:
            return
        from app.database.connection import session_scope
        from app.models.pickup import Pickup
        with session_scope() as s:
            path = s.get(Pickup, p.id).signed_file
        if path and Path(path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            warn(self, t('Fichier introuvable.'))
