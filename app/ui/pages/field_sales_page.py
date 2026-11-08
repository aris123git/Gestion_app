"""Ventes en tournée : sorties du matin, retour du soir (écart), commissions cumulées, boutiques visitées, vendeurs."""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from app.i18n import t
from app.models.field_sales import RULE_FIXED, RULE_PERCENT, RUN_CLOSED, RUN_OPEN, SCOPE_CATEGORY, SCOPE_DEFAULT, SCOPE_PRODUCT, VISIT_RESULTS
from app.services import audit_service, field_sales_service as fs, permissions as perms, settings_service
from app.ui.dialogs.chantier_dialog import _money
from app.ui.pages.rentals_page import _cell, _date_edit, _table
from app.ui.state import AppState
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import confirm, info, make_card, page_title, warn
from app.utils.helpers import format_money


def _qty() -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(3)
    s.setRange(0, 1_000_000)
    s.setGroupSeparatorShown(True)
    return s


class SellerDialog(QDialog):
    def __init__(self, parent=None, seller=None):
        super().__init__(parent)
        self.setWindowTitle(t("Vendeur"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=380, min_height=240, preferred_width=460, preferred_height=280)
        form = QFormLayout(self)
        self.name = QLineEdit(seller.name if seller else "")
        self.phone = QLineEdit(seller.phone if seller else "")
        self.active = QCheckBox(t("Actif"))
        self.active.setChecked(seller.active if seller else True)
        form.addRow(t("Nom"), self.name)
        form.addRow(t("Téléphone (WhatsApp)"), self.phone)
        form.addRow("", self.active)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self) -> dict:
        return dict(name=self.name.text(), phone=self.phone.text(), active=self.active.isChecked())


class OutDialog(QDialog):
    """Sortie du matin : vendeur + produits emportés (ajout libre, au fil de la saisie)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Nouvelle sortie"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=620, min_height=520, preferred_width=720, preferred_height=640)
        self.choices = fs.product_choices()
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.seller = QComboBox()
        for s in fs.list_sellers():
            self.seller.addItem(s.name, s.id)
        form.addRow(t("Vendeur"), self.seller)
        root.addLayout(form)
        root.addWidget(QLabel(f"<b>{t('Produits emportés')}</b>"))
        self.table = _table(["Produit", "Quantité", "Prix de vente", "Disponible"])
        self.table.setColumnWidth(0, 280)
        root.addWidget(self.table, 1)
        self._widgets: list = []
        add = QPushButton(t("+ Ajouter un produit"))
        add.clicked.connect(self._add_row)
        root.addWidget(add)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText(t("Note (facultatif)"))
        root.addWidget(self.notes)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self._add_row()

    def _add_row(self) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        combo = QComboBox()
        combo.setEditable(True)
        for c in self.choices:
            combo.addItem(c.name, c.id)
        combo.setCurrentIndex(-1)
        qty, price = _qty(), _money()
        avail = QLabel()
        combo.currentIndexChanged.connect(lambda _i, c=combo, p=price, a=avail: self._fill(c, p, a))
        for col, w in ((0, combo), (1, qty), (2, price), (3, avail)):
            self.table.setCellWidget(r, col, w)
        self._widgets.append((combo, qty, price))

    def _fill(self, combo, price, avail) -> None:
        pid = combo.currentData()
        ch = next((c for c in self.choices if c.id == pid), None)
        if ch:
            price.setValue(ch.price)
            avail.setText(f"{ch.available:g}")

    def values(self) -> tuple:
        lines = [fs.LineInput(c.currentData(), q.value(), p.value()) for c, q, p in self._widgets if c.currentData() and q.value() > 0]
        return self.seller.currentData(), lines, self.notes.text()


class CloseDialog(QDialog):
    """Retour du soir : ce qui est revenu, l'argent remis, l'écart et la commission en direct."""

    def __init__(self, parent, run_id: int, currency: str):
        super().__init__(parent)
        self.run_id, self.currency = run_id, currency
        self.setWindowTitle(t("Retour du soir"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=640, min_height=560, preferred_width=760, preferred_height=680)
        self.lines = fs.get_run_lines(run_id)
        root = QVBoxLayout(self)
        self.table = _table(["Produit", "Sorti", "Revenu", "Vendu", "Prix de vente", "Montant"])
        self.table.setRowCount(len(self.lines))
        self.backs, self.prices = {}, {}
        for r, l in enumerate(self.lines):
            self.table.setItem(r, 0, _cell(l.product_name))
            self.table.setItem(r, 1, _cell(f"{float(l.qty_out):g}", True))
            back = _qty()
            back.setMaximum(float(l.qty_out))
            price = _money()
            price.setValue(float(l.unit_price))
            back.valueChanged.connect(self._update)
            price.valueChanged.connect(self._update)
            self.table.setCellWidget(r, 2, back)
            self.table.setCellWidget(r, 4, price)
            self.table.setItem(r, 3, _cell("", True))
            self.table.setItem(r, 5, _cell("", True))
            self.backs[l.id], self.prices[l.id] = back, price
        root.addWidget(self.table, 1)
        form = QFormLayout()
        self.cash = _money()
        self.cash.valueChanged.connect(self._update)
        form.addRow(t("Argent remis par le vendeur"), self.cash)
        root.addLayout(form)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.charge = QCheckBox(t("Mettre le manque à la charge du vendeur (devient sa dette)"))
        root.addWidget(self.charge)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(t("Clôturer la sortie"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self._update()

    def _inputs(self) -> tuple:
        return {k: v.value() for k, v in self.backs.items()}, {k: v.value() for k, v in self.prices.items()}

    def _update(self, *_a) -> None:
        backs, prices = self._inputs()
        try:
            prev = fs.preview_close(self.run_id, backs, prices, self.cash.value())
        except ValueError as exc:
            self.summary.setText(f"<span style='color:#b91c1c'>{exc}</span>")
            return
        m = lambda v: format_money(v, self.currency)  # noqa: E731
        for r, x in enumerate(prev.lines):
            self.table.item(r, 3).setText(f"{x.sold:g}")
            self.table.item(r, 5).setText(m(x.value))
        if prev.shortage > 0.0005:
            gap = f"<b style='color:#b91c1c'>{t('Manque')} : {m(prev.shortage)}</b>"
        elif prev.shortage < -0.0005:
            gap = f"<b style='color:#15803d'>{t('Surplus')} : {m(-prev.shortage)}</b>"
        else:
            gap = f"<b style='color:#15803d'>{t('Compte juste')}</b>"
        self.charge.setEnabled(prev.shortage > 0.0005)
        if not self.charge.isEnabled():
            self.charge.setChecked(False)
        self.summary.setText(f"{t('Argent attendu')} : <b>{m(prev.expected)}</b> &nbsp;·&nbsp; {t('remis')} : {m(prev.cash)} &nbsp;·&nbsp; {gap}"
                             f"<br/>{t('Commission du vendeur')} : <b>{m(prev.commission)}</b>")

    def values(self) -> dict:
        backs, prices = self._inputs()
        return dict(backs=backs, prices=prices, cash_received=self.cash.value(), charge_shortage=self.charge.isChecked())


class VisitDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Boutique visitée"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=420, min_height=420, preferred_width=500, preferred_height=500)
        form = QFormLayout(self)
        self.shop = QLineEdit()
        self.phone = QLineEdit()
        self.area = QLineEdit()
        self.result = QComboBox()
        for r in VISIT_RESULTS:
            self.result.addItem(t(r), r)
        self.amount = _money()
        self.has_follow = QCheckBox(t("Rappeler le"))
        self.follow = QDateEdit(QDate.currentDate().addDays(3))
        self.follow.setCalendarPopup(True)
        self.follow.setDisplayFormat("dd/MM/yyyy")
        self.note = QLineEdit()
        for label, w in ((t("Boutique"), self.shop), (t("Téléphone"), self.phone), (t("Quartier"), self.area), (t("Résultat"), self.result),
                         (t("Montant vendu"), self.amount)):
            form.addRow(label, w)
        form.addRow(self.has_follow, self.follow)
        form.addRow(t("Note"), self.note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self) -> dict:
        d = self.follow.date()
        return dict(shop=self.shop.text(), phone=self.phone.text(), area=self.area.text(), result=self.result.currentData(),
                    amount=self.amount.value(), note=self.note.text(),
                    follow_up=datetime(d.year(), d.month(), d.day()) if self.has_follow.isChecked() else None)


class RuleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Règle de commission"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=460, min_height=320, preferred_width=520, preferred_height=360)
        from sqlalchemy import select
        from app.database.connection import session_scope
        from app.models.category import Category
        form = QFormLayout(self)
        self.scope = QComboBox()
        self.scope.addItem(t("Un produit"), SCOPE_PRODUCT)
        self.scope.addItem(t("Une catégorie"), SCOPE_CATEGORY)
        self.scope.addItem(t("Tous les autres produits (par défaut)"), SCOPE_DEFAULT)
        self.target = QComboBox()
        self.kind = QComboBox()
        self.kind.addItem(t("Pourcentage du prix de vente"), RULE_PERCENT)
        self.kind.addItem(t("Montant fixe par unité vendue"), RULE_FIXED)
        self.value = _money()
        self.value.setDecimals(2)
        with session_scope() as session:
            self.products = [(p.id, p.name) for p in fs.product_choices()]
            self.categories = [(c.id, c.name) for c in session.scalars(select(Category).order_by(Category.name))]
        self.scope.currentIndexChanged.connect(self._fill)
        form.addRow(t("S'applique à"), self.scope)
        form.addRow(t("Choix"), self.target)
        form.addRow(t("Type"), self.kind)
        form.addRow(t("Valeur"), self.value)
        hint = QLabel(t("Pourcentage : 5 = 5 %.  Montant fixe : 500 = 500 par carton vendu.  0 pour supprimer la règle."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b;")
        form.addRow(hint)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self._fill()

    def _fill(self, *_a) -> None:
        scope = self.scope.currentData()
        self.target.clear()
        self.target.setEnabled(scope != SCOPE_DEFAULT)
        for rid, name in (self.products if scope == SCOPE_PRODUCT else self.categories if scope == SCOPE_CATEGORY else []):
            self.target.addItem(name, rid)

    def values(self) -> tuple:
        scope = self.scope.currentData()
        return scope, (None if scope == SCOPE_DEFAULT else self.target.currentData()), self.kind.currentData(), self.value.value()


class FieldSalesPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.can_manage = state.can(perms.MANAGE_FIELD_SALES)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(page_title(t("Ventes en tournée")))
        self.banner = QLabel()
        self.banner.setTextFormat(Qt.TextFormat.RichText)
        self.banner.setWordWrap(True)
        layout.addWidget(make_card(self.banner))
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_runs(), t("Sorties"))
        self.tabs.addTab(self._build_commissions(), t("Commissions"))
        self.tabs.addTab(self._build_prospects(), t("Boutiques"))
        self.tabs.addTab(self._build_sellers(), t("Vendeurs"))

    def _user(self):
        return self.state.user_id, getattr(self.state.current_user, "username", "")

    def _cur(self) -> str:
        return settings_service.get_shop_info().currency or "FCFA"

    def _data_changed(self) -> None:
        notify = getattr(self.state, "notify_data_changed", None)
        if notify:
            notify()

    # -- sorties ----------------------------------------------------------------------------------
    def _build_runs(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.f_status = QComboBox()
        self.f_status.addItem(t("Toutes"), None)
        self.f_status.addItem(t("En tournée"), RUN_OPEN)
        self.f_status.addItem(t("Clôturées"), RUN_CLOSED)
        self.f_status.currentIndexChanged.connect(self.refresh)
        new = QPushButton(t("+ Nouvelle sortie"))
        new.setObjectName("Primary")
        new.setEnabled(self.can_manage)
        new.clicked.connect(self._new_run)
        bar.addWidget(self.f_status)
        bar.addStretch()
        bar.addWidget(new)
        lay.addLayout(bar)
        self.runs = _table(["N°", "Vendeur", "Sortie", "Produits", "Statut", "Attendu", "Remis", "Écart", "Commission"])
        lay.addWidget(self.runs, 1)
        row = QHBoxLayout()
        self.b_close = QPushButton(t("Retour du soir"))
        self.b_close.setObjectName("Primary")
        self.b_add = QPushButton(t("Ajouter des produits"))
        self.b_visit = QPushButton(t("+ Boutique visitée"))
        self.b_cancel = QPushButton(t("Annuler la sortie"))
        self.b_cancel.setObjectName("Danger")
        self.b_close.clicked.connect(self._close_run)
        self.b_add.clicked.connect(self._add_products)
        self.b_visit.clicked.connect(self._visit)
        self.b_cancel.clicked.connect(self._cancel_run)
        for b in (self.b_close, self.b_add, self.b_visit, self.b_cancel):
            b.setEnabled(self.can_manage)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        return w

    def _run_id(self):
        r = self.runs.currentRow()
        return self.runs.item(r, 0).data(Qt.ItemDataRole.UserRole) if r >= 0 else None

    def _run_status(self):
        r = self.runs.currentRow()
        return self.runs.item(r, 4).data(Qt.ItemDataRole.UserRole) if r >= 0 else None

    def _new_run(self) -> None:
        dlg = OutDialog(self)
        if dlg.seller.count() == 0:
            warn(self, t("Ajoutez d'abord un vendeur (onglet Vendeurs)."))
            return
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        seller_id, lines, notes = dlg.values()
        try:
            rid = fs.open_run(seller_id, lines, notes=notes, user_id=self.state.user_id)
        except ValueError as exc:
            warn(self, str(exc))
            return
        audit_service.log_action("Sortie en tournée", "FieldRun", str(rid), *self._user())
        self.refresh()

    def _add_products(self) -> None:
        rid = self._run_id()
        if not rid or self._run_status() != RUN_OPEN:
            return
        choices = [c for c in fs.product_choices() if c.available > 0]
        names = [f"{c.name} ({c.available:g})" for c in choices]
        if not names:
            warn(self, t("Aucun produit disponible."))
            return
        pick, ok = QInputDialog.getItem(self, t("Ajouter"), t("Produit"), names, 0, False)
        if not ok:
            return
        ch = choices[names.index(pick)]
        qty, ok = QInputDialog.getDouble(self, t("Ajouter"), t("Quantité"), 1, 0.001, ch.available, 3)
        if not ok:
            return
        try:
            fs.add_to_run(rid, ch.id, qty)
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()

    def _close_run(self) -> None:
        rid = self._run_id()
        if not rid or self._run_status() != RUN_OPEN:
            return
        dlg = CloseDialog(self, rid, self._cur())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            prev = fs.close_run(rid, user_id=self.state.user_id, **dlg.values())
        except ValueError as exc:
            warn(self, str(exc))
            return
        audit_service.log_action("Clôture de tournée", "FieldRun", str(rid), *self._user())
        self._data_changed()
        self.refresh()
        info(self, t("Sortie clôturée. La vente est enregistrée dans la caisse."))

    def _cancel_run(self) -> None:
        rid = self._run_id()
        if rid and self._run_status() == RUN_OPEN and confirm(self, t("Annuler cette sortie ? Rien n'a été retiré du stock.")):
            fs.cancel_run(rid)
            self.refresh()

    def _visit(self) -> None:
        rid = self._run_id()
        if not rid:
            return
        dlg = VisitDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            fs.add_visit(rid, **dlg.values())
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()

    # -- commissions -------------------------------------------------------------------------------------
    def _build_commissions(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.comm = _table(["Vendeur", "Sorties", "Commission due", "Dette du vendeur"])
        lay.addWidget(self.comm, 1)
        self.comm_hint = QLabel()
        self.comm_hint.setWordWrap(True)
        self.comm_hint.setStyleSheet("color: #64748b;")
        lay.addWidget(self.comm_hint)
        row = QHBoxLayout()
        self.b_day = QPushButton(t("Payer aujourd'hui"))
        self.b_days = QPushButton(t("Payer les N derniers jours…"))
        self.b_range = QPushButton(t("Payer une période…"))
        self.b_all = QPushButton(t("Tout payer"))
        self.b_wa = QPushButton(t("Contacter (WhatsApp)"))
        self.b_day.clicked.connect(lambda: self._pay("day"))
        self.b_days.clicked.connect(lambda: self._pay("days"))
        self.b_range.clicked.connect(lambda: self._pay("range"))
        self.b_all.clicked.connect(lambda: self._pay("all"))
        self.b_wa.clicked.connect(lambda: self._contact(self._comm_seller()))
        for b in (self.b_day, self.b_days, self.b_range, self.b_all):
            b.setEnabled(self.can_manage)
            row.addWidget(b)
        row.addWidget(self.b_wa)
        row.addStretch()
        lay.addLayout(row)
        self.deduct = QCheckBox(t("Déduire la dette du vendeur de la commission"))
        self.deduct.setChecked(True)
        lay.addWidget(self.deduct)
        self.on_cash = QCheckBox(t("Calculer la commission sur l'argent réellement rapporté (réduite en proportion s'il manque de l'argent)"))
        self.on_cash.setChecked(fs.commission_on_cash())
        self.on_cash.setEnabled(self.can_manage)
        self.on_cash.toggled.connect(fs.set_commission_on_cash)
        lay.addWidget(self.on_cash)
        lay.addWidget(QLabel(f"<b>{t('Règles de commission')}</b>"))
        self.rules = _table(["S'applique à", "Type", "Valeur"])
        self.rules.setMaximumHeight(170)
        lay.addWidget(self.rules)
        row = QHBoxLayout()
        add = QPushButton(t("+ Règle"))
        rm = QPushButton(t("Supprimer la règle"))
        add.clicked.connect(self._add_rule)
        rm.clicked.connect(self._remove_rule)
        for b in (add, rm):
            b.setEnabled(self.can_manage)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        return w

    def _comm_seller(self):
        r = self.comm.currentRow()
        return self.comm.item(r, 0).data(Qt.ItemDataRole.UserRole) if r >= 0 else None

    def _pay(self, mode: str) -> None:
        sid = self._comm_seller()
        if not sid:
            warn(self, t("Sélectionnez un vendeur."))
            return
        start = end = None
        if mode == "day":
            start, end = fs.day_range(datetime.now())
        elif mode == "days":
            n, ok = QInputDialog.getInt(self, t("Payer"), t("Nombre de derniers jours (aujourd'hui compris) :"), 7, 1, 365)
            if not ok:
                return
            end = fs.day_range(datetime.now())[1]
            start = end - timedelta(days=n)
        elif mode == "range":
            dlg = QDialog(self)
            dlg.setWindowTitle(t("Période à payer"))
            form = QFormLayout(dlg)
            a, b = _date_edit(-6), _date_edit(0)
            form.addRow(t("Du"), a)
            form.addRow(t("Au (inclus)"), b)
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            form.addRow(bb)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            qa, qb = a.date(), b.date()
            start, end = datetime(qa.year(), qa.month(), qa.day()), datetime(qb.year(), qb.month(), qb.day()) + timedelta(days=1)
        due = next((r for r in fs.commission_due(start, end) if r.seller_id == sid), None)
        if due is None or due.gross <= 0:
            warn(self, t("Aucune commission à payer pour ce vendeur sur cette période."))
            return
        if not confirm(self, f"{t('Marquer payée la commission de')} {self.comm.item(self.comm.currentRow(), 0).text()} : "
                             f"{format_money(due.gross, self._cur())} ({due.runs} {t('sortie(s)')}) ?"):
            return
        try:
            pay = fs.pay_commission(sid, start, end, deduct_debt=self.deduct.isChecked(), user_id=self.state.user_id, username=self._user()[1])
        except ValueError as exc:
            warn(self, str(exc))
            return
        audit_service.log_action("Commission payée", "FieldSeller", str(sid), *self._user())
        self._data_changed()
        self.refresh()
        info(self, f"{t('Net à remettre au vendeur')} : {format_money(pay.net_paid, self._cur())}"
                   + (f" ({t('dette déduite')} {format_money(pay.debt_deducted, self._cur())})" if pay.debt_deducted else ""))

    def _add_rule(self) -> None:
        dlg = RuleDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            fs.set_rule(*dlg.values())
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()

    def _remove_rule(self) -> None:
        r = self.rules.currentRow()
        if r >= 0:
            fs.delete_rule(self.rules.item(r, 0).data(Qt.ItemDataRole.UserRole))
            self.refresh()

    # -- boutiques -------------------------------------------------------------------------------------------
    def _build_prospects(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.prospects = _table(["Boutique", "Téléphone", "Quartier", "Dernier résultat", "À rappeler le", "Visites", "Total vendu"])
        lay.addWidget(self.prospects, 1)
        row = QHBoxLayout()
        wa = QPushButton(t("Contacter (WhatsApp)"))
        wa.clicked.connect(self._contact_shop)
        row.addWidget(wa)
        row.addStretch()
        lay.addLayout(row)
        return w

    def _contact_shop(self) -> None:
        r = self.prospects.currentRow()
        if r < 0:
            return
        phone = self.prospects.item(r, 1).text()
        from app.services import messaging_service as ms
        try:
            link = ms.whatsapp_link(phone, f"Bonjour, c'est {settings_service.get_shop_info().name or ''}. ")
        except ValueError as exc:
            warn(self, str(exc))
            return
        QDesktopServices.openUrl(QUrl(link))

    # -- vendeurs -------------------------------------------------------------------------------------------------
    def _build_sellers(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.sellers = _table(["Nom", "Téléphone", "Dette", "Actif"])
        lay.addWidget(self.sellers, 1)
        row = QHBoxLayout()
        add = QPushButton(t("+ Ajouter un vendeur"))
        add.setObjectName("Primary")
        edit = QPushButton(t("Modifier"))
        wa = QPushButton(t("Contacter (WhatsApp)"))
        rm = QPushButton(t("Supprimer"))
        rm.setObjectName("Danger")
        add.clicked.connect(lambda: self._seller_dialog(None))
        edit.clicked.connect(lambda: self._seller_dialog(self._current_seller()))
        wa.clicked.connect(lambda: self._contact(self._seller_id()))
        rm.clicked.connect(self._seller_delete)
        for b in (add, edit, rm):
            b.setEnabled(self.can_manage)
            row.addWidget(b)
        row.insertWidget(3, wa)
        row.addStretch()
        lay.addLayout(row)
        return w

    def _seller_id(self):
        r = self.sellers.currentRow()
        return self.sellers.item(r, 0).data(Qt.ItemDataRole.UserRole) if r >= 0 else None

    def _current_seller(self):
        sid = self._seller_id()
        return next((s for s in fs.list_sellers(True) if s.id == sid), None) if sid else None

    def _seller_dialog(self, seller) -> None:
        dlg = SellerDialog(self, seller)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            fs.save_seller(seller_id=seller.id if seller else None, **dlg.values())
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()

    def _seller_delete(self) -> None:
        s = self._current_seller()
        if s and confirm(self, t("Supprimer ce vendeur ?")):
            try:
                fs.delete_seller(s.id)
            except ValueError as exc:
                warn(self, str(exc))
                return
            self.refresh()

    def _contact(self, seller_id) -> None:
        """Ouvre WhatsApp sur la conversation du vendeur, message pré-rempli (point sur sa commission)."""
        if not seller_id:
            warn(self, t("Sélectionnez un vendeur."))
            return
        try:
            link = fs.seller_whatsapp_link(seller_id, fs.seller_message(seller_id))
        except ValueError as exc:
            warn(self, str(exc))
            return
        QDesktopServices.openUrl(QUrl(link))

    # -- affichage ----------------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        cur = self._cur()
        rows = fs.list_runs(status=self.f_status.currentData())
        self.runs.setRowCount(len(rows))
        for r, x in enumerate(rows):
            closed = x.status == RUN_CLOSED
            gap = ""
            color = None
            if closed:
                if x.shortage > 0.0005:
                    gap, color = f"- {format_money(x.shortage, cur)}" + (f" ({t('dette')})" if x.charged else ""), "#b91c1c"
                elif x.shortage < -0.0005:
                    gap, color = f"+ {format_money(-x.shortage, cur)}", "#15803d"
                else:
                    gap = t("Juste")
            cells = [x.number, x.seller, x.out_at.strftime("%d/%m %H:%M"), x.items, t("Clôturée") if closed else t("En tournée"),
                     format_money(x.expected, cur) if closed else "", format_money(x.cash, cur) if closed else "", gap,
                     (format_money(x.commission, cur) + (f" ({t('payée')})" if x.commission_paid else "")) if closed else ""]
            for c, v in enumerate(cells):
                it = _cell(v, c in (5, 6, 7, 8), x.id if c == 0 else None, color if c == 7 else None)
                if c == 4:
                    it.setData(Qt.ItemDataRole.UserRole, x.status)
                self.runs.setItem(r, c, it)
        due = fs.commission_due()
        self.comm.setRowCount(len(due))
        for r, d in enumerate(due):
            for c, v in enumerate([d.seller, d.runs, format_money(d.gross, cur), format_money(d.debt, cur)]):
                self.comm.setItem(r, c, _cell(v, c > 0, d.seller_id if c == 0 else None))
        self.comm_hint.setText(t("« Payer » marque payées les commissions de la période et les enregistre dans les dépenses."))
        rules = fs.list_rules()
        self.rules.setRowCount(len(rules))
        for r, rule in enumerate(rules):
            value = f"{rule['value']:g} %" if rule["kind"] == RULE_PERCENT else f"{format_money(rule['value'], cur)} / {t('unité')}"
            for c, v in enumerate([rule["target"], t("Pourcentage") if rule["kind"] == RULE_PERCENT else t("Montant fixe"), value]):
                self.rules.setItem(r, c, _cell(v, c == 2, rule["id"] if c == 0 else None))
        pros = fs.prospects()
        self.prospects.setRowCount(len(pros))
        now = datetime.now()
        for r, p in enumerate(pros):
            late = p.follow_up is not None and p.follow_up <= now
            cells = [p.shop, p.phone, p.area, t(p.last_result), p.follow_up.strftime("%d/%m/%Y") if p.follow_up else "", p.visits, format_money(p.total, cur)]
            for c, v in enumerate(cells):
                self.prospects.setItem(r, c, _cell(v, c in (5, 6), None, "#b91c1c" if (late and c == 4) else None))
        sellers = fs.list_sellers(True)
        self.sellers.setRowCount(len(sellers))
        for r, s in enumerate(sellers):
            for c, v in enumerate([s.name, s.phone, format_money(fs.seller_debt(s.id), cur), t("Oui") if s.active else t("Non")]):
                self.sellers.setItem(r, c, _cell(v, c == 2, s.id if c == 0 else None))
        out = [x for x in fs.list_runs(status=RUN_OPEN)]
        total_due = sum(d.gross for d in due)
        reminders = sum(1 for p in pros if p.follow_up is not None and p.follow_up <= now and p.last_result in ("Intéressé", "À rappeler"))
        parts = [f"<b>{len(out)}</b> {t('sortie(s) en cours')}", f"{t('Commissions à payer')} : <b>{format_money(total_due, cur)}</b>"]
        if reminders:
            parts.append(f"<span style='color:#b45309'><b>{reminders}</b> {t('boutique(s) à rappeler')}</span>")
        self.banner.setText(" &nbsp;·&nbsp; ".join(parts))
