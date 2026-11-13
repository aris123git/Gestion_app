"""Gaz : cahier des détaillants, grossistes (livraisons, paiements, vides à rendre), produits et prix, pertes."""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from app.i18n import t
from app.services import audit_service, gas_service as gs, permissions as perms
from app.ui.pages.rentals_page import _cell, _date_edit, _table
from app.ui.state import AppState
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import info, page_title, warn


def _money(v) -> str:
    return f"{round(float(v or 0)):,}".replace(",", " ")


def _amount_spin(maximum=100_000_000) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(0)
    s.setRange(0, maximum)
    s.setGroupSeparatorShown(True)
    return s


def _line_combo(price: str | None = None) -> QComboBox:
    c = QComboBox()
    for ln in gs.list_lines():
        c.addItem(f"{ln.name}  (stock {ln.stock})", ln.id)
    return c


class _Form(QDialog):
    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.setWindowTitle(t(title))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=380, min_height=220, preferred_width=460, preferred_height=300)
        self.form = QFormLayout(self)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._ok)
        self.buttons.rejected.connect(self.reject)

    def finish(self) -> None:
        self.form.addRow(self.buttons)

    def _ok(self) -> None:
        try:
            self.apply()
        except gs.GasError as exc:
            warn(self, str(exc))
            return
        self.accept()

    def apply(self) -> None:  # pragma: no cover
        raise NotImplementedError


class SaleDialog(_Form):
    """Vente anonyme à un détaillant : produit, quantité, prix modifiable."""

    def __init__(self, parent, day: date):
        super().__init__(parent, "Vente détaillant")
        self.day = day
        self.line = _line_combo()
        self.qty = QSpinBox()
        self.qty.setRange(1, 100000)
        self.price = _amount_spin()
        self.line.currentIndexChanged.connect(self._price)
        self._price()
        self.form.addRow(t("Produit"), self.line)
        self.form.addRow(t("Quantité"), self.qty)
        self.form.addRow(t("Prix unitaire"), self.price)
        self.finish()

    def _price(self) -> None:
        lid = self.line.currentData()
        for ln in gs.list_lines():
            if ln.id == lid:
                self.price.setValue(ln.retail_price)

    def apply(self) -> None:
        if self.line.currentData() is None:
            raise gs.GasError("Créez d'abord les produits gaz.")
        gs.retail_sale(self.line.currentData(), self.qty.value(), self.price.value(), _at(self.day))


def _at(day: date) -> datetime:
    now = datetime.now()
    return datetime(day.year, day.month, day.day, now.hour, now.minute, now.second)


class EntryDialog(_Form):
    def __init__(self, parent, day: date):
        super().__init__(parent, "Entrée en stock")
        self.day = day
        self.line = _line_combo()
        self.qty = QSpinBox()
        self.qty.setRange(1, 1_000_000)
        self.reason = QLineEdit()
        self.form.addRow(t("Produit"), self.line)
        self.form.addRow(t("Quantité pleine reçue"), self.qty)
        self.form.addRow(t("Note"), self.reason)
        self.finish()

    def apply(self) -> None:
        if self.line.currentData() is None:
            raise gs.GasError("Créez d'abord les produits gaz.")
        gs.add_entry(self.line.currentData(), self.qty.value(), _at(self.day), self.reason.text())


class LossDialog(_Form):
    def __init__(self, parent, day: date):
        super().__init__(parent, "Perte de bouteilles")
        self.day = day
        self.line = _line_combo()
        self.qty = QSpinBox()
        self.qty.setRange(1, 100000)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(t("Motif (fuite, casse, vol…)"))
        self.form.addRow(t("Produit"), self.line)
        self.form.addRow(t("Nombre de bouteilles"), self.qty)
        self.form.addRow(t("Motif"), self.reason)
        self.form.addRow(QLabel(t("Perte supportée par l'entreprise : rien n'est facturé.")))
        self.finish()

    def apply(self) -> None:
        if self.line.currentData() is None:
            raise gs.GasError("Créez d'abord les produits gaz.")
        gs.record_loss(self.line.currentData(), self.qty.value(), self.reason.text(), _at(self.day))


class WholesalerDialog(_Form):
    def __init__(self, parent, row=None):
        super().__init__(parent, "Grossiste")
        self.row = row
        self.name = QLineEdit(row.name if row else "")
        self.phone = QLineEdit(row.phone if row else "")
        self.address = QLineEdit(row.address if row else "")
        self.notes = QLineEdit(row.notes if row else "")
        for label, w in (("Nom", self.name), ("Téléphone", self.phone), ("Adresse", self.address), ("Notes", self.notes)):
            self.form.addRow(t(label), w)
        self.finish()

    def apply(self) -> None:
        gs.save_wholesaler(self.name.text(), self.phone.text(), self.address.text(), self.notes.text(), self.row.id if self.row else None)


class DeliveryDialog(_Form):
    """Livraison à un grossiste : quantités par produit (prix du grossiste, modifiable), vides rendues, payé."""

    def __init__(self, parent, wholesaler_id: int, day: date):
        super().__init__(parent, "Livraison au grossiste")
        self.wid, self.day = wholesaler_id, day
        fit_dialog_to_screen(self, min_width=520, min_height=360, preferred_width=620, preferred_height=520)
        self.rows = []
        for ln in gs.list_lines():
            qty = QSpinBox()
            qty.setRange(0, 100000)
            price = _amount_spin()
            price.setValue(ln.wholesale_price)
            back = QSpinBox()
            back.setRange(0, 100000)
            h = QHBoxLayout()
            for lab, w in (("pleines", qty), ("P.U", price), ("vides rendues", back)):
                h.addWidget(QLabel(t(lab)))
                h.addWidget(w)
            qty.valueChanged.connect(lambda v, b=back: b.setValue(v))   # par défaut autant de vides que de pleines (modifiable)
            self.form.addRow(f"{ln.name} (stock {ln.stock})", h)
            self.rows.append((ln.id, qty, price, back))
        self.paid = _amount_spin()
        self.form.addRow(t("Payé maintenant"), self.paid)
        self.note = QLineEdit()
        self.form.addRow(t("Note"), self.note)
        self.finish()

    def apply(self) -> None:
        items = [(lid, q.value(), p.value(), b.value()) for lid, q, p, b in self.rows if q.value() > 0]
        gs.deliver(self.wid, items, _at(self.day), self.paid.value(), self.note.text())


class PayDialog(_Form):
    def __init__(self, parent, wholesaler_id: int, day: date):
        super().__init__(parent, "Paiement du grossiste")
        self.wid, self.day = wholesaler_id, day
        self.amount = _amount_spin()
        self.note = QLineEdit()
        self.form.addRow(t("Montant"), self.amount)
        self.form.addRow(t("Note"), self.note)
        self.finish()

    def apply(self) -> None:
        gs.pay(self.wid, self.amount.value(), _at(self.day), self.note.text())


class LineDialog(_Form):
    def __init__(self, parent, row=None):
        super().__init__(parent, "Produit gaz")
        self.row = row
        self.size = QDoubleSpinBox()
        self.size.setDecimals(1)
        self.size.setRange(0.5, 100)
        self.size.setValue(row.size_kg if row else 6)
        self.formula = QComboBox()
        for key, label in gs.FORMULAS.items():
            self.formula.addItem(label, key)
        if row:
            self.formula.setCurrentIndex(self.formula.findData(row.formula))
        self.retail = _amount_spin()
        self.retail.setValue(row.retail_price if row else 0)
        self.wholesale = _amount_spin()
        self.wholesale.setValue(row.wholesale_price if row else 0)
        self.has_cost = QCheckBox(t("Prix d'achat connu (pour calculer le bénéfice)"))
        self.cost = _amount_spin()
        self.has_cost.setChecked(bool(row and row.cost_price is not None))
        self.cost.setValue(row.cost_price if row and row.cost_price is not None else 0)
        self.cost.setEnabled(self.has_cost.isChecked())
        self.has_cost.toggled.connect(self.cost.setEnabled)
        self.active = QCheckBox(t("Actif"))
        self.active.setChecked(row.active if row else True)
        for label, w in (("Taille (kg)", self.size), ("Formule", self.formula), ("Prix détaillant", self.retail),
                         ("Prix grossiste", self.wholesale), ("", self.has_cost), ("Prix d'achat", self.cost), ("", self.active)):
            self.form.addRow(t(label) if label else "", w)
        self.finish()

    def apply(self) -> None:
        gs.save_line(self.size.value(), self.formula.currentData(), self.retail.value(), self.wholesale.value(),
                     self.cost.value() if self.has_cost.isChecked() else None, self.row.id if self.row else None, self.active.isChecked())


class GasPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.can_manage = state.can(perms.MANAGE_GAS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(page_title(t("Gaz")))
        bar = QHBoxLayout()
        bar.addWidget(QLabel(t("Jour")))
        self.day = _date_edit()
        self.day.dateChanged.connect(self.refresh)
        bar.addWidget(self.day)
        bar.addStretch()
        layout.addLayout(bar)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # Détaillants : cahier du jour
        tab = QWidget()
        v = QVBoxLayout(tab)
        self.sheet = _table(["Produit", "S.I", "Entrée", "S.T", "Vente", "P.U", "Montant", "Livré grossistes", "Pertes", "S.F"])
        v.addWidget(self.sheet, 1)
        self.total_label = QLabel()
        v.addWidget(self.total_label)
        v.addLayout(self._buttons([("sell", "+ Vente détaillant", self._sell, True), ("entry", "+ Entrée en stock", self._entry, False),
                                   ("loss", "Déclarer une perte", self._loss, False)]))
        self.tabs.addTab(tab, t("Détaillants"))

        # Grossistes
        tab = QWidget()
        v = QVBoxLayout(tab)
        self.wtable = _table(["Grossiste", "Livré", "Vides rendues", "Total livré", "Payé", "Reste à payer", "Situation"])
        self.wtable.doubleClicked.connect(lambda *_: self._deliver())
        v.addWidget(self.wtable, 1)
        v.addWidget(QLabel(t("Livraisons du jour (feuille « Entrée »)")))
        self.dtable = _table(["Grossiste", "Pleines", "Vides rendues", "Total"])
        v.addWidget(self.dtable, 1)
        v.addLayout(self._buttons([("wnew", "+ Nouveau grossiste", self._wnew, False), ("wedit", "Modifier", self._wedit, False),
                                   ("deliver", "Livrer", self._deliver, True), ("pay", "Encaisser un paiement", self._pay, False)]))
        self.tabs.addTab(tab, t("Grossistes"))

        # Produits & prix
        tab = QWidget()
        v = QVBoxLayout(tab)
        self.ltable = _table(["Produit", "Prix détaillant", "Prix grossiste", "Prix d'achat", "Stock"])
        self.ltable.doubleClicked.connect(lambda *_: self._ledit())
        v.addWidget(self.ltable, 1)
        v.addLayout(self._buttons([("lnew", "+ Produit", self._lnew, False), ("ledit", "Modifier prix", self._ledit, True),
                                   ("lstd", "Créer 6 kg / 12,5 kg × 3 formules", self._lstd, False)]))
        self.tabs.addTab(tab, t("Produits & prix"))
        self.refresh()

    def _buttons(self, spec) -> QHBoxLayout:
        row = QHBoxLayout()
        if not hasattr(self, "btn"):
            self.btn = {}
        for key, label, slot, primary in spec:
            b = QPushButton(t(label))
            if primary:
                b.setObjectName("Primary")
            b.clicked.connect(slot)
            b.setEnabled(self.can_manage)
            self.btn[key] = b
            row.addWidget(b)
        row.addStretch()
        return row

    def _day(self) -> date:
        d = self.day.date()
        return date(d.year(), d.month(), d.day())

    def _log(self, action: str, ref: str) -> None:
        audit_service.log_action(action, "gaz", ref, self.state.user_id, getattr(self.state.current_user, "username", ""))

    def _run(self, dlg: QDialog, action: str) -> None:
        if dlg.exec():
            self._log(action, "")
            self.refresh()

    def _sell(self): self._run(SaleDialog(self, self._day()), "Vente gaz détaillant")
    def _entry(self): self._run(EntryDialog(self, self._day()), "Entrée stock gaz")
    def _loss(self): self._run(LossDialog(self, self._day()), "Perte gaz")
    def _wnew(self): self._run(WholesalerDialog(self), "Grossiste gaz")
    def _lnew(self): self._run(LineDialog(self), "Produit gaz")

    def _selected(self, table):
        r = table.currentRow()
        it = table.item(r, 0) if r >= 0 else None
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _wedit(self):
        wid = self._selected(self.wtable)
        row = next((w for w in gs.list_wholesalers(False) if w.id == wid), None)
        if row:
            self._run(WholesalerDialog(self, row), "Grossiste gaz")

    def _deliver(self):
        wid = self._selected(self.wtable)
        if wid is None:
            info(self, t("Choisissez un grossiste."))
        elif self.can_manage:
            self._run(DeliveryDialog(self, wid, self._day()), "Livraison gaz")

    def _pay(self):
        wid = self._selected(self.wtable)
        if wid is None:
            info(self, t("Choisissez un grossiste."))
        else:
            self._run(PayDialog(self, wid, self._day()), "Paiement gaz")

    def _ledit(self):
        lid = self._selected(self.ltable)
        row = next((r for r in gs.list_lines(False) if r.id == lid), None)
        if row:
            self._run(LineDialog(self, row), "Produit gaz")

    def _lstd(self):
        n = gs.create_standard_lines()
        info(self, t("{n} produit(s) créé(s). Renseignez les prix.").format(n=n) if n else t("Les produits standard existent déjà."))
        self.refresh()

    def refresh(self, *_a) -> None:
        day = self._day()
        rows = gs.day_sheet(day)
        self.sheet.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r["name"], r["si"], r["entry"], r["st"], r["sold"], _money(r["unit_price"]), _money(r["amount"]),
                    r["delivered"], r["lost"], r["sf"]]
            for j, val in enumerate(vals):
                self.sheet.setItem(i, j, _cell(val, right=j > 0))
        self.total_label.setText(f"<b>{t('Total du jour (détaillants)')} : {_money(gs.day_total(day))} F</b>")
        ws = gs.list_wholesalers(False)
        self.wtable.setRowCount(len(ws))
        for i, w in enumerate(ws):
            a = gs.wholesaler_account(w.id)
            vals = [w.name, a.delivered, a.empties_back, _money(a.amount_due), _money(a.paid), _money(a.balance), a.statement]
            for j, val in enumerate(vals):
                self.wtable.setItem(i, j, _cell(val, right=0 < j < 6, data=w.id if j == 0 else None))
        ds = gs.deliveries_of_day(day)
        self.dtable.setRowCount(len(ds))
        for i, d in enumerate(ds):
            for j, val in enumerate([d["wholesaler"], sum(d["lines"].values()), d["empties_back"], _money(d["total"])]):
                self.dtable.setItem(i, j, _cell(val, right=j > 0))
        ls = gs.list_lines(False)
        self.ltable.setRowCount(len(ls))
        for i, ln in enumerate(ls):
            cost = "—" if ln.cost_price is None else _money(ln.cost_price)
            for j, val in enumerate([ln.name, _money(ln.retail_price), _money(ln.wholesale_price), cost, ln.stock]):
                self.ltable.setItem(i, j, _cell(val, right=j > 0, data=ln.id if j == 0 else None))
