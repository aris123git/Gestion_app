"""Gaz : cahier des détaillants, grossistes (livraisons, paiements, vides à rendre), produits et prix, pertes."""

from __future__ import annotations

import tempfile
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from app.i18n import t
from app.services import audit_service, gas_service as gs, permissions as perms
from app.ui.pages.rentals_page import _cell, _date_edit, _table
from app.ui.state import AppState
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import info, make_card, page_title, warn


def _money(v) -> str:
    return f"{round(float(v or 0)):,}".replace(",", " ")


def _amount_spin(maximum=100_000_000) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(0)
    s.setRange(0, maximum)
    s.setGroupSeparatorShown(True)
    return s


def _line_combo(trip_id: int | None = None) -> QComboBox:
    c = QComboBox()
    for ln in gs.list_lines(trip_id=trip_id):
        c.addItem(f"{ln.name} — stock {ln.stock}", ln.id)
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
    """Vente anonyme à un détaillant : plusieurs produits d'un coup, prix modifiable (par défaut le prix détaillant)."""

    def __init__(self, parent, day: date, trip_id: int | None = None):
        super().__init__(parent, "Vente détaillant")
        self.day, self.trip_id = day, trip_id
        fit_dialog_to_screen(self, min_width=520, min_height=360, preferred_width=640, preferred_height=520)
        self.rows = []
        for ln in gs.list_lines(trip_id=trip_id):
            qty = QSpinBox()
            qty.setRange(0, 100000)
            price = _amount_spin()
            price.setValue(ln.retail_price)
            h = QHBoxLayout()
            for lab, w in (("quantité", qty), ("P.U", price)):
                h.addWidget(QLabel(t(lab)))
                h.addWidget(w)
            self.form.addRow(f"{ln.name} — stock {ln.stock}", h)
            self.rows.append((ln.id, qty, price))
        self.finish()

    def apply(self) -> None:
        items = [(lid, q.value(), p.value()) for lid, q, p in self.rows if q.value() > 0]
        if not self.rows:
            raise gs.GasError("Créez d'abord les produits gaz.")
        gs.retail_sales(items, _at(self.day), self.trip_id)


def _at(day: date) -> datetime:
    now = datetime.now()
    return datetime(day.year, day.month, day.day, now.hour, now.minute, now.second)


class EntryDialog(_Form):
    def __init__(self, parent, day: date, trip_id: int | None = None):
        super().__init__(parent, "Chargement du camion" if trip_id else "Entrée en stock")
        self.day, self.trip_id = day, trip_id
        self.line = _line_combo(trip_id)
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
        gs.add_entry(self.line.currentData(), self.qty.value(), _at(self.day), self.reason.text(), self.trip_id)


class LossDialog(_Form):
    def __init__(self, parent, day: date, trip_id: int | None = None):
        super().__init__(parent, "Perte de bouteilles")
        self.day, self.trip_id = day, trip_id
        self.line = _line_combo(trip_id)
        self.qty = QSpinBox()
        self.qty.setRange(1, 100000)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(t("Motif : fuite, casse, vol…"))
        self.form.addRow(t("Produit"), self.line)
        self.form.addRow(t("Nombre de bouteilles"), self.qty)
        self.form.addRow(t("Motif"), self.reason)
        self.form.addRow(QLabel(t("Perte supportée par l'entreprise : rien n'est facturé.")))
        self.finish()

    def apply(self) -> None:
        if self.line.currentData() is None:
            raise gs.GasError("Créez d'abord les produits gaz.")
        gs.record_loss(self.line.currentData(), self.qty.value(), self.reason.text(), _at(self.day), self.trip_id)


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

    def __init__(self, parent, wholesaler_id: int, day: date, trip_id: int | None = None):
        super().__init__(parent, "Livraison au grossiste")
        self.wid, self.day, self.trip_id = wholesaler_id, day, trip_id
        fit_dialog_to_screen(self, min_width=520, min_height=360, preferred_width=620, preferred_height=520)
        self.rows = []
        for ln in gs.list_lines(trip_id=trip_id):
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
            self.form.addRow(f"{ln.name} — stock {ln.stock}", h)
            self.rows.append((ln.id, qty, price, back))
        self.paid = _amount_spin()
        self.form.addRow(t("Payé maintenant"), self.paid)
        self.note = QLineEdit()
        self.form.addRow(t("Note"), self.note)
        self.finish()

    def apply(self) -> None:
        items = [(lid, q.value(), p.value(), b.value()) for lid, q, p, b in self.rows if q.value() > 0]
        gs.deliver(self.wid, items, _at(self.day), self.paid.value(), self.note.text(), self.trip_id)


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


class TripDialog(_Form):
    """Nouveau voyage = retour du camion + nouveau chargement.

    S'il y a un voyage en cours, il est terminé ici : on propose les vides à remettre à la source (modifiables) et les
    pleines restantes passent dans le nouveau voyage."""

    def __init__(self, parent, day: date):
        super().__init__(parent, "Nouveau voyage")
        self.day = day
        self.previous = gs.current_trip_id()
        fit_dialog_to_screen(self, min_width=480, min_height=380, preferred_width=580, preferred_height=620)
        self.return_rows, self.count_rows = [], []
        self.reason = QLineEdit()
        if self.previous:
            prev = gs.get_trip(self.previous)
            self.form.addRow(QLabel(f"<b>{t('Retour du camion')} — {prev.label}</b>"))
            self.form.addRow(QLabel(t("Le papier doit correspondre au camion. Comptez ce qui est dans le camion et les vides remises : tout écart doit être justifié.")))
            names = {ln.id: ln.name for ln in gs.list_lines(False)}
            for lid, expected in gs.trip_expected(self.previous).items():
                sp = QSpinBox()
                sp.setRange(0, 1_000_000)
                sp.setValue(expected)
                self.form.addRow(f"{names.get(lid, '?')} — {t('pleines comptées, attendues')} {expected}", sp)
                self.count_rows.append((lid, expected, sp))
            for size, qty in gs.empties_on_hand().items():
                sp = QSpinBox()
                sp.setRange(0, 1_000_000)
                sp.setValue(qty)
                self.form.addRow(f"{size:g} kg".replace(".", ",") + f" — {t('vides remises, attendues')} {qty}", sp)
                self.return_rows.append((size, sp))
            self.reason.setPlaceholderText(t("Justification en cas d'écart"))
            self.form.addRow(t("Justification"), self.reason)
            self.form.addRow(QLabel(f"<b>{t('Nouveau chargement')}</b>"))
        self.truck, self.driver, self.source = QLineEdit(), QLineEdit(), QLineEdit("SONABHY")
        self.form.addRow(t("Camion"), self.truck)
        self.form.addRow(t("Chauffeur"), self.driver)
        self.form.addRow(t("Chargé à"), self.source)
        self.rows = []
        for ln in gs.list_lines():
            q = QSpinBox()
            q.setRange(0, 1_000_000)
            self.form.addRow(f"{ln.name} " + t("chargées"), q)
            self.rows.append((ln.id, q))
        self.finish()

    def apply(self) -> None:
        handed = {size: sp.value() for size, sp in self.return_rows} if self.previous else None
        counted = {lid: sp.value() for lid, _e, sp in self.count_rows} if self.previous else None
        self.trip_id = gs.start_trip([(lid, q.value()) for lid, q in self.rows], self.truck.text(), self.driver.text(), self.source.text(),
                                     _at(self.day), handed=handed, counted=counted, reason=self.reason.text())


class AdjustDialog(_Form):
    """Ajuster le stock du camion d'après un comptage : la quantité comptée remplace celle du logiciel, avec un motif obligatoire."""

    def __init__(self, parent, day: date, trip_id: int):
        super().__init__(parent, "Ajuster le stock")
        self.day, self.trip_id = day, trip_id
        self.stock = {ln.id: ln.stock for ln in gs.list_lines(trip_id=trip_id)}
        self.line = _line_combo(trip_id)
        self.counted = QSpinBox()
        self.counted.setRange(0, 1_000_000)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(t("Motif obligatoire"))
        self.line.currentIndexChanged.connect(self._sync)
        self._sync()
        self.form.addRow(t("Produit"), self.line)
        self.form.addRow(t("Quantité comptée dans le camion"), self.counted)
        self.form.addRow(t("Motif"), self.reason)
        self.finish()

    def _sync(self) -> None:
        self.counted.setValue(self.stock.get(self.line.currentData(), 0))

    def apply(self) -> None:
        lid = self.line.currentData()
        if lid is None:
            raise gs.GasError("Créez d'abord les produits gaz.")
        gs.adjust_stock(lid, self.counted.value() - self.stock.get(lid, 0), self.reason.text(), _at(self.day), self.trip_id)


class TripEditDialog(_Form):
    def __init__(self, parent, trip_id: int):
        super().__init__(parent, "Modifier le voyage")
        self.trip_id = trip_id
        tr = gs.get_trip(trip_id)
        self.truck, self.driver, self.source, self.note = QLineEdit(tr.truck), QLineEdit(tr.driver), QLineEdit(tr.source), QLineEdit(tr.note)
        for label, w in (("Camion", self.truck), ("Chauffeur", self.driver), ("Chargé à", self.source), ("Notes", self.note)):
            self.form.addRow(t(label), w)
        self.finish()

    def apply(self) -> None:
        gs.update_trip(self.trip_id, self.truck.text(), self.driver.text(), self.source.text(), self.note.text())


class TripDaysDialog(QDialog):
    """Étapes jour par jour d'un voyage."""

    def __init__(self, parent, trip_id: int):
        super().__init__(parent)
        trip = gs.get_trip(trip_id)
        self.setWindowTitle(f"{t('Étapes du voyage')} {trip.number}")
        fit_dialog_to_screen(self, min_width=640, min_height=420, preferred_width=780, preferred_height=560)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"<b>{trip.label}</b> — {t('chargé')} {trip.loaded}, {t('restant')} {trip.remaining}"))
        self.table = _table(["Jour", "Étape", "Détail", "Montant"])
        v.addWidget(self.table, 1)
        rows = []
        for d in gs.trip_days(trip_id):
            for st in d["steps"]:
                detail = ", ".join(f"{n} × {q}" for n, q in st["lines"].items()) + (f" — {'; '.join(st['reasons'])}" if st["reasons"] else "")
                rows.append((f"{d['date']:%d/%m/%Y}", st["who"], detail, _money(st["amount"]) if st["amount"] else ""))
            rows.append(("", t("Total du jour"), "", _money(d["total"])))
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, val in enumerate(r):
                self.table.setItem(i, j, _cell(val, right=j == 3))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        bb.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        v.addWidget(bb)


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
        self.has_cost = QCheckBox(t("Prix d'achat connu, pour calculer le bénéfice"))
        self.cost = _amount_spin()
        self.has_cost.setChecked(bool(row and row.cost_price is not None))
        self.cost.setValue(row.cost_price if row and row.cost_price is not None else 0)
        self.cost.setEnabled(self.has_cost.isChecked())
        self.has_cost.toggled.connect(self.cost.setEnabled)
        self.active = QCheckBox(t("Actif"))
        self.active.setChecked(row.active if row else True)
        for label, w in (("Taille en kg", self.size), ("Formule", self.formula), ("Prix détaillant", self.retail),
                         ("Prix grossiste", self.wholesale), ("", self.has_cost), ("Prix d'achat", self.cost), ("", self.active)):
            self.form.addRow(t(label) if label else "", w)
        self.finish()

    def apply(self) -> None:
        gs.save_line(self.size.value(), self.formula.currentData(), self.retail.value(), self.wholesale.value(),
                     self.cost.value() if self.has_cost.isChecked() else None, self.row.id if self.row else None, self.active.isChecked())


class ProductsDialog(QDialog):
    """Produits gaz et prix : réglés une fois, rarement modifiés."""

    def __init__(self, page: "GasPage"):
        super().__init__(page)
        self.page = page
        self.setWindowTitle(t("Produits et prix"))
        fit_dialog_to_screen(self, min_width=640, min_height=420, preferred_width=780, preferred_height=520)
        v = QVBoxLayout(self)
        self.ltable = _table(["Produit", "Prix détaillant", "Prix grossiste", "Prix d'achat", "Stock"])
        self.ltable.verticalHeader().setVisible(False)
        self.ltable.doubleClicked.connect(lambda *_: self._edit())
        v.addWidget(self.ltable, 1)
        row = QHBoxLayout()
        for label, slot, primary in (("+ Produit", self._new, False), ("Modifier prix", self._edit, True),
                                     ("Créer 6 kg / 12,5 kg × 3 formules", self._standard, False)):
            b = QPushButton(t(label))
            if primary:
                b.setObjectName("Primary")
            b.setEnabled(page.can_manage)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        self._fill()

    def _fill(self) -> None:
        ls = gs.list_lines(False)
        self.ltable.setRowCount(len(ls))
        for i, ln in enumerate(ls):
            cost = "—" if ln.cost_price is None else _money(ln.cost_price)
            for j, val in enumerate([ln.name, _money(ln.retail_price), _money(ln.wholesale_price), cost, ln.stock]):
                self.ltable.setItem(i, j, _cell(val, right=j > 0, data=ln.id if j == 0 else None))

    def _after(self) -> None:
        self._fill()
        self.page.refresh()

    def _new(self) -> None:
        self.page._run(LineDialog(self), "Produit gaz")
        self._fill()

    def _edit(self) -> None:
        r = self.ltable.currentRow()
        it = self.ltable.item(r, 0) if r >= 0 else None
        row = next((x for x in gs.list_lines(False) if it and x.id == it.data(Qt.ItemDataRole.UserRole)), None)
        if row:
            self.page._run(LineDialog(self, row), "Produit gaz")
            self._fill()

    def _standard(self) -> None:
        n = gs.create_standard_lines()
        info(self, t("{n} produit(s) créé(s). Renseignez les prix.").format(n=n) if n else t("Les produits standard existent déjà."))
        self._after()


class GasPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.can_manage = state.can(perms.MANAGE_GAS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(page_title(t("Gaz")))
        top.addStretch()
        prod = QPushButton(t("Produits et prix"))
        prod.clicked.connect(lambda: ProductsDialog(self).exec())
        top.addWidget(prod)
        top.addWidget(QLabel(t("Jour")))
        self.day = _date_edit()
        self.day.dateChanged.connect(self.refresh)
        top.addWidget(self.day)
        layout.addLayout(top)
        kp = QHBoxLayout()
        self.k_truck, self.k_sales, self.k_due = QLabel(), QLabel(), QLabel()
        for k in (self.k_truck, self.k_sales, self.k_due):
            k.setTextFormat(Qt.TextFormat.RichText)
            kp.addWidget(make_card(k), 1)
        layout.addLayout(kp)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # Détaillants : cahier du jour
        tab = QWidget()
        v = QVBoxLayout(tab)
        head = QHBoxLayout()
        head.addLayout(self._buttons([("sell", "+ Vente détaillant", self._sell, True),
                                      ("loss", "Déclarer une perte", self._loss, False), ("psheet", "Imprimer le cahier", self._print_sheet, False)]), 1)
        self.total_label = QLabel()
        head.addWidget(self.total_label)
        v.addLayout(head)
        self.sheet = _table(["Produit", "S.I", "Entrée", "S.T", "Vente", "P.U", "Montant", "Livré grossistes", "Pertes", "S.F"])
        self.sheet.verticalHeader().setVisible(False)
        v.addWidget(self.sheet, 1)
        self.tabs.addTab(tab, t("Détaillants"))

        # Grossistes : liste + détail
        tab = QWidget()
        v = QVBoxLayout(tab)
        bar = QHBoxLayout()
        bar.addStretch()
        bar.addLayout(self._buttons([("wnew", "+ Nouveau grossiste", self._wnew, True)]))
        v.addLayout(bar)
        body = QHBoxLayout()
        self.wtable = _table(["Grossiste", "Livré", "Vides rendues", "Reste à payer"])
        self.wtable.verticalHeader().setVisible(False)
        self.wtable.doubleClicked.connect(lambda *_: self._deliver())
        self.wtable.currentCellChanged.connect(lambda *_: self._show_wholesaler())
        body.addWidget(self.wtable, 3)
        side = QVBoxLayout()
        self.w_head = QLabel(t("Choisissez un grossiste."))
        self.w_head.setTextFormat(Qt.TextFormat.RichText)
        self.w_head.setWordWrap(True)
        side.addWidget(self.w_head)
        side.addWidget(QLabel(f"<b>{t('Livraisons du jour')}</b>"))
        self.dtable = _table(["Produit", "Pleines", "Vides rendues", "Total"])
        self.dtable.verticalHeader().setVisible(False)
        side.addWidget(self.dtable, 1)
        side.addLayout(self._buttons([("deliver", "Livrer", self._deliver, True), ("pay", "Encaisser un paiement", self._pay, False)]))
        side.addLayout(self._buttons([("pstate", "Relevé PDF", self._print_statement, False), ("psend", "Envoyer le relevé", self._send_statement, False),
                                      ("wedit", "Modifier", self._wedit, False)]))
        body.addLayout(side, 2)
        v.addLayout(body, 1)
        self.tabs.addTab(tab, t("Grossistes"))

        # Camion : voyages + étapes
        tab = QWidget()
        v = QVBoxLayout(tab)
        bar = QHBoxLayout()
        self.empties_label = QLabel()
        bar.addWidget(self.empties_label, 1)
        bar.addLayout(self._buttons([("tnew", "+ Nouveau voyage", self._tnew, True)]))
        v.addLayout(bar)
        body = QHBoxLayout()
        self.ttable = _table(["N°", "Camion", "Chauffeur", "Départ", "Statut", "Chargé", "Restant"])
        self.ttable.verticalHeader().setVisible(False)
        self.ttable.doubleClicked.connect(lambda *_: self._tdays())
        self.ttable.currentCellChanged.connect(lambda *_: self._show_trip())
        body.addWidget(self.ttable, 3)
        side = QVBoxLayout()
        self.t_head = QLabel(t("Choisissez un voyage."))
        self.t_head.setTextFormat(Qt.TextFormat.RichText)
        self.t_head.setWordWrap(True)
        side.addWidget(self.t_head)
        side.addWidget(QLabel(f"<b>{t('Étapes par jour')}</b>"))
        self.t_steps = _table(["Jour", "Étape", "Montant"])
        self.t_steps.verticalHeader().setVisible(False)
        side.addWidget(self.t_steps, 1)
        side.addLayout(self._buttons([("tload", "Charger", self._tload, True), ("tprint", "Imprimer le bandeau", self._print_trip, False)]))
        side.addLayout(self._buttons([("tadj", "Ajuster le stock", self._tadjust, False), ("tedit", "Modifier le voyage", self._tedit, False)]))
        body.addLayout(side, 2)
        v.addLayout(body, 1)
        self.tabs.addTab(tab, t("Camion"))

        # Suivi : opérations du jour (annulation) + chiffres et pertes de la période
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.addWidget(QLabel(f"<b>{t('Opérations du jour')}</b>"))
        self.jtable = _table(["Heure", "Opération", "Détail", "Montant", "Voyage"])
        self.jtable.verticalHeader().setVisible(False)
        v.addWidget(self.jtable, 1)
        v.addLayout(self._buttons([("jcancel", "Annuler l'opération", self._cancel_op, False)]))
        pbar = QHBoxLayout()
        pbar.addWidget(QLabel(f"<b>{t('Période')}</b> &nbsp; {t('Du')}"))
        self.f_start = _date_edit()
        self.f_start.setDate(QDate.currentDate().addDays(-QDate.currentDate().day() + 1))
        pbar.addWidget(self.f_start)
        pbar.addWidget(QLabel(t("au")))
        self.f_end = _date_edit()
        pbar.addWidget(self.f_end)
        pbar.addStretch()
        v.addLayout(pbar)
        self.figures_label = QLabel()
        self.figures_label.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.figures_label)
        v.addWidget(QLabel(f"<b>{t('Pertes de la période')}</b>"))
        self.losstable = _table(["Date", "Produit", "Bouteilles", "Motif"])
        self.losstable.verticalHeader().setVisible(False)
        v.addWidget(self.losstable, 1)
        v.addLayout(self._buttons([("ploss", "Imprimer les pertes", self._print_losses, False)]))
        self.f_start.dateChanged.connect(self._refresh_states)
        self.f_end.dateChanged.connect(self._refresh_states)
        self.tabs.addTab(tab, t("Suivi"))
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

    def _trip(self):
        """Tout le stock gaz est dans le camion : le voyage en cours."""
        return gs.current_trip_id()

    def _need_trip(self):
        tid = self._trip()
        if tid is None:
            info(self, t("Créez d'abord un voyage dans l'onglet Camion : tout le stock se trouve dans le camion."))
        return tid

    def _sell(self):
        tid = self._need_trip()
        if tid:
            self._run(SaleDialog(self, self._day(), tid), "Vente gaz détaillant")

    def _loss(self):
        tid = self._need_trip()
        if tid:
            self._run(LossDialog(self, self._day(), tid), "Perte gaz")

    def _tnew(self):
        dlg = TripDialog(self, self._day())
        if dlg.exec():
            self._log("Voyage gaz", "")
            self.refresh()

    def _tload(self):
        tid = self._selected(self.ttable) or self._need_trip()
        if tid is None:
            return
        if gs.get_trip(tid).status != "en_cours":
            info(self, t("Ce voyage est terminé."))
        else:
            self._run(EntryDialog(self, self._day(), tid), "Chargement camion gaz")

    def _tadjust(self):
        tid = self._need_trip()
        if tid:
            self._run(AdjustDialog(self, self._day(), tid), "Ajustement stock gaz")

    def _tedit(self):
        tid = self._selected(self.ttable) or self._trip()
        if tid is None:
            info(self, t("Choisissez un voyage."))
        else:
            self._run(TripEditDialog(self, tid), "Voyage gaz modifié")

    def _cancel_op(self):
        from PySide6.QtWidgets import QInputDialog

        r = self.jtable.currentRow()
        it = self.jtable.item(r, 0) if r >= 0 else None
        if it is None:
            info(self, t("Choisissez une opération."))
            return
        kind, ref = it.data(Qt.ItemDataRole.UserRole)
        reason, ok = QInputDialog.getText(self, t("Annuler l'opération"), t("Motif de l'annulation :"))
        if not ok:
            return
        try:
            gs.cancel_operation(kind, ref, reason)
        except gs.GasError as exc:
            warn(self, str(exc))
            return
        self._log("Annulation gaz", f"{kind} {ref} : {reason.strip()}")
        self.refresh()

    def _tdays(self):
        tid = self._selected(self.ttable)
        if tid is None:
            info(self, t("Choisissez un voyage."))
        else:
            TripDaysDialog(self, tid).exec()
    def _wnew(self): self._run(WholesalerDialog(self), "Grossiste gaz")

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
            tid = self._need_trip()
            if tid:
                self._run(DeliveryDialog(self, wid, self._day(), tid), "Livraison gaz")

    def _pay(self):
        wid = self._selected(self.wtable)
        if wid is None:
            info(self, t("Choisissez un grossiste."))
        else:
            self._run(PayDialog(self, wid, self._day()), "Paiement gaz")

    def _open(self, path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _tmp(self, name: str) -> Path:
        return Path(tempfile.gettempdir()) / name

    def _print_sheet(self):
        from PySide6.QtWidgets import QMessageBox

        from app.printers import gas_docs

        box = QMessageBox(self)
        box.setWindowTitle(t("Imprimer le cahier"))
        box.setText(t("Quelle partie imprimer ?"))
        det = box.addButton(t("Détaillants"), QMessageBox.ButtonRole.AcceptRole)
        gro = box.addButton(t("Grossistes"), QMessageBox.ButtonRole.AcceptRole)
        both = box.addButton(t("Les deux"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(t("Annuler"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        part = {det: "detaillants", gro: "grossistes", both: "both"}.get(box.clickedButton())
        if part:
            self._open(gas_docs.build_day_sheet(self._day(), self._tmp(f"gaz_cahier_{part}.pdf"), None, part))

    def _print_statement(self):
        from app.printers import gas_docs

        wid = self._selected(self.wtable)
        if wid is None:
            info(self, t("Choisissez un grossiste."))
        else:
            self._open(gas_docs.build_wholesaler_statement(wid, self._tmp(f"gaz_releve_{wid}.pdf")))

    def _send_statement(self):
        from app.printers import gas_docs
        from app.ui.dialogs.send_document_dialog import SendDocumentDialog

        wid = self._selected(self.wtable)
        if wid is None:
            info(self, t("Choisissez un grossiste."))
            return
        row = next((w for w in gs.list_wholesalers(False) if w.id == wid), None)
        acc = gs.wholesaler_account(wid)
        path = gas_docs.build_wholesaler_statement(wid, self._tmp(f"gaz_releve_{wid}.pdf"))
        message = f"Bonjour {acc.name}, voici votre situation à ce jour : {acc.statement}. Le relevé détaillé est joint."
        SendDocumentDialog(self, path, row.phone if row else "", "", f"Relevé {acc.name}", message, "Envoyer le relevé").exec()

    def _print_trip(self):
        from app.printers import gas_docs

        tid = self._selected(self.ttable)
        if tid is None:
            info(self, t("Choisissez un voyage."))
        else:
            self._open(gas_docs.build_trip_bandeau(tid, self._tmp(f"gaz_voyage_{tid}.pdf")))

    def _print_losses(self):
        from app.printers import gas_docs

        self._open(gas_docs.build_losses(*self._period(), self._tmp("gaz_pertes.pdf")))

    def _period(self):
        a, b = self.f_start.date(), self.f_end.date()
        return date(a.year(), a.month(), a.day()), date(b.year(), b.month(), b.day())

    def _refresh_states(self, *_a) -> None:
        start, end = self._period()
        f = gs.figures(start, end)
        profit = t("bénéfice non calculé (renseignez les prix d'achat)") if f["profit"] is None else f"{_money(f['profit'])} F"
        inc = t("inclus dans les chiffres généraux") if gs.include_in_totals() else t("à part des chiffres généraux")
        self.figures_label.setText(
            f"<b>{t('Chiffre d affaires gaz')} :</b> {_money(f['revenue'])} F &nbsp; <b>{t('Encaissé')} :</b> {_money(f['cash'])} F &nbsp; "
            f"<b>{t('Dettes des grossistes')} :</b> {_money(f['debts'])} F &nbsp; <b>{t('Bénéfice')} :</b> {profit}<br><i>{inc}</i>")
        rows = gs.losses(start, end)
        self.losstable.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, val in enumerate([f"{r['date']:%d/%m/%Y}", r["line"], r["qty"], r["reason"]]):
                self.losstable.setItem(i, j, _cell(val, right=j == 2))

    def _select_by_id(self, table, ident) -> None:
        for r in range(table.rowCount()):
            it = table.item(r, 0)
            if it is not None and it.data(Qt.ItemDataRole.UserRole) == ident:
                table.selectRow(r)
                return
        if table.rowCount():
            table.selectRow(0)

    def _show_wholesaler(self) -> None:
        wid = self._selected(self.wtable)
        self.dtable.setRowCount(0)
        if wid is None:
            self.w_head.setText(t("Choisissez un grossiste."))
            return
        a = gs.wholesaler_account(wid)
        color = "#b91c1c" if a.balance > 0 else "#15803d"
        self.w_head.setText(f"<b style='font-size:15px'>{a.name}</b><br><span style='color:{color}'>{a.statement}</span>")
        names = {ln.id: ln.name for ln in gs.list_lines(False)}
        rows = []
        for d in gs.deliveries_of_day(self._day(), wid):
            for lid, qty in d["lines"].items():
                rows.append((names.get(lid, "?"), qty, d["empties_back"], _money(d["total"])))
        self.dtable.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, val in enumerate(r):
                self.dtable.setItem(i, j, _cell(val, right=j > 0))

    def _show_trip(self) -> None:
        tid = self._selected(self.ttable)
        self.t_steps.setRowCount(0)
        if tid is None:
            self.t_head.setText(t("Choisissez un voyage."))
            return
        tr = gs.get_trip(tid)
        self.t_head.setText(f"<b style='font-size:15px'>{tr.label}</b><br>{t('Chargé')} {tr.loaded} · {t('Restant')} {tr.remaining}")
        rows = []
        for d in gs.trip_days(tid):
            for st in d["steps"]:
                rows.append((f"{d['date']:%d/%m}", st["who"], _money(st["amount"]) if st["amount"] else ""))
        self.t_steps.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, val in enumerate(r):
                self.t_steps.setItem(i, j, _cell(val, right=j == 2))

    def refresh(self, *_a) -> None:
        day = self._day()
        keep_w, keep_t = self._selected(self.wtable), self._selected(self.ttable)
        rows = [r for r in gs.day_sheet(day, all_sources=True)
                if any(r[k] for k in ("si", "entry", "sold", "delivered", "lost", "sf"))]
        self.sheet.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r["name"], r["si"], r["entry"], r["st"], r["sold"], _money(r["unit_price"]), _money(r["amount"]),
                    r["delivered"], r["lost"], r["sf"]]
            for j, val in enumerate(vals):
                self.sheet.setItem(i, j, _cell(val, right=j > 0))
        retail = gs.day_total(day, all_sources=True)
        self.total_label.setText(f"<b>{t('Total du jour, détaillants')} : {_money(retail)} F</b>")
        for w in (self.wtable, self.ttable):
            w.blockSignals(True)
        ws = gs.list_wholesalers(False)
        self.wtable.setRowCount(len(ws))
        due = 0.0
        for i, w in enumerate(ws):
            a = gs.wholesaler_account(w.id)
            due += max(0.0, a.balance)
            vals = [w.name, a.delivered, a.empties_back, _money(a.balance)]
            for j, val in enumerate(vals):
                self.wtable.setItem(i, j, _cell(val, right=j > 0, data=w.id if j == 0 else None))
        delivered_today = sum(d["total"] for d in gs.deliveries_of_day(day))
        ops = gs.day_operations(day)
        self.jtable.setRowCount(len(ops))
        for i, o in enumerate(ops):
            for j, val in enumerate([f"{o['when']:%H:%M}", o["label"], o["detail"], _money(o["amount"]) if o["amount"] else "", o["trip"]]):
                self.jtable.setItem(i, j, _cell(val, right=j == 3, data=(o["kind"], o["id"]) if j == 0 else None))
        hand = gs.empties_on_hand()
        parts = [f"{format(k, 'g').replace('.', ',')} kg : {v}" for k, v in hand.items()]
        self.empties_label.setText(f"<b>{t('Vides en possession')} :</b> " + (", ".join(parts) or t("aucune")))
        ts = gs.list_trips()
        self.ttable.setRowCount(len(ts))
        for i, tr in enumerate(ts):
            for j, val in enumerate([tr.number, tr.truck, tr.driver, f"{tr.started_at:%d/%m/%Y}", t("En cours") if tr.status == "en_cours" else t("Terminé"),
                                     tr.loaded, tr.remaining]):
                self.ttable.setItem(i, j, _cell(val, right=j >= 5, data=tr.id if j == 0 else None))
        for w in (self.wtable, self.ttable):
            w.blockSignals(False)
        in_truck = sum(tr.remaining for tr in ts if tr.status == "en_cours")
        grey = "<span style='color:#64748b'>%s</span><br><b style='font-size:24px'>%s</b>"
        self.k_truck.setText(grey % (t("Bouteilles dans le camion"), in_truck))
        self.k_sales.setText(grey % (t("Ventes du jour"), f"{_money(retail + delivered_today)} F"))
        self.k_due.setText(grey % (t("Reste à encaisser (grossistes)"), f"{_money(due)} F"))
        self._select_by_id(self.wtable, keep_w)
        self._select_by_id(self.ttable, keep_t)
        self._show_wholesaler()
        self._show_trip()
        self._refresh_states()
