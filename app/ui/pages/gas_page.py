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
from app.ui.widgets.helpers import info, page_title, warn


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

    def __init__(self, parent, day: date, trip_id: int | None = None):
        super().__init__(parent, "Vente détaillant")
        self.day, self.trip_id = day, trip_id
        self.line = _line_combo(trip_id)
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
        gs.retail_sale(self.line.currentData(), self.qty.value(), self.price.value(), _at(self.day), self.trip_id)


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
        self.reason.setPlaceholderText(t("Motif (fuite, casse, vol…)"))
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
            self.form.addRow(f"{ln.name} (stock {ln.stock})", h)
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
    """Nouveau voyage : camion, chauffeur, source et chargement (pleines par produit)."""

    def __init__(self, parent, day: date):
        super().__init__(parent, "Nouveau voyage")
        self.day = day
        fit_dialog_to_screen(self, min_width=460, min_height=360, preferred_width=560, preferred_height=520)
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
        self.trip_id = gs.start_trip([(lid, q.value()) for lid, q in self.rows], self.truck.text(), self.driver.text(), self.source.text(), _at(self.day))


class CloseTripDialog(_Form):
    """Retour à la source : vides proposées d'après les livraisons, modifiables ; échange sans argent."""

    def __init__(self, parent, trip_id: int):
        super().__init__(parent, "Retour du camion")
        self.trip_id = trip_id
        trip = gs.get_trip(trip_id)
        self.form.addRow(QLabel(f"<b>{trip.label}</b>"))
        self.form.addRow(QLabel(t("Les vides à remettre sont calculées d'après les livraisons et ventes (modifiables). C'est un échange : aucun argent.")))
        self.rows = []
        for size, qty in gs.empties_proposed(trip_id).items():
            sp = QSpinBox()
            sp.setRange(0, 1_000_000)
            sp.setValue(qty)
            self.form.addRow(f"{size:g} kg".replace(".", ",") + " — " + t("vides remises"), sp)
            self.rows.append((size, sp))
        left = sum(r["remaining"] for r in gs.trip_summary(trip_id))
        self.form.addRow(QLabel(t("Pleines restant dans le camion (retournent au dépôt) : {n}").format(n=left)))
        self.finish()

    def apply(self) -> None:
        gs.close_trip(self.trip_id, {size: sp.value() for size, sp in self.rows})


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
                detail = ", ".join(f"{n} × {q}" for n, q in st["lines"].items()) + (f" ({'; '.join(st['reasons'])})" if st["reasons"] else "")
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
        bar.addWidget(QLabel(t("Stock")))
        self.source = QComboBox()
        self.source.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.source)
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
                                   ("loss", "Déclarer une perte", self._loss, False), ("psheet", "Imprimer le cahier", self._print_sheet, False)]))
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
                                   ("deliver", "Livrer", self._deliver, True), ("pay", "Encaisser un paiement", self._pay, False),
                                   ("pstate", "Relevé PDF", self._print_statement, False)]))
        self.tabs.addTab(tab, t("Grossistes"))

        # Camion : voyages
        tab = QWidget()
        v = QVBoxLayout(tab)
        self.ttable = _table(["N°", "Camion", "Chauffeur", "Départ", "Statut", "Chargé", "Restant"])
        self.ttable.doubleClicked.connect(lambda *_: self._tdays())
        v.addWidget(self.ttable, 1)
        v.addLayout(self._buttons([("tnew", "+ Nouveau voyage", self._tnew, True), ("tload", "Charger", self._tload, False),
                                   ("tclose", "Retour du camion (vides)", self._tclose, False), ("tdays", "Étapes par jour", self._tdays, False),
                                   ("tprint", "Imprimer le bandeau", self._print_trip, False)]))
        self.tabs.addTab(tab, t("Camion"))

        # États : chiffres gaz (à part) et pertes
        tab = QWidget()
        v = QVBoxLayout(tab)
        pbar = QHBoxLayout()
        pbar.addWidget(QLabel(t("Du")))
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
        v.addWidget(QLabel(t("Pertes de la période")))
        self.losstable = _table(["Date", "Produit", "Bouteilles", "Motif"])
        v.addWidget(self.losstable, 1)
        v.addLayout(self._buttons([("ploss", "Imprimer les pertes", self._print_losses, False)]))
        self.f_start.dateChanged.connect(self._refresh_states)
        self.f_end.dateChanged.connect(self._refresh_states)
        self.tabs.addTab(tab, t("États"))

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

    def _trip(self):
        return self.source.currentData()

    def _sell(self): self._run(SaleDialog(self, self._day(), self._trip()), "Vente gaz détaillant")
    def _entry(self): self._run(EntryDialog(self, self._day(), self._trip()), "Entrée stock gaz")
    def _loss(self): self._run(LossDialog(self, self._day(), self._trip()), "Perte gaz")

    def _tnew(self):
        dlg = TripDialog(self, self._day())
        if dlg.exec():
            self._log("Voyage gaz", "")
            self.refresh()
            i = self.source.findData(dlg.trip_id)
            if i >= 0:
                self.source.setCurrentIndex(i)      # on travaille tout de suite sur le stock du camion

    def _tload(self):
        tid = self._selected(self.ttable)
        if tid is None:
            info(self, t("Choisissez un voyage."))
        else:
            self._run(EntryDialog(self, self._day(), tid), "Chargement camion gaz")

    def _tclose(self):
        tid = self._selected(self.ttable)
        if tid is None:
            info(self, t("Choisissez un voyage."))
        elif gs.get_trip(tid).status != "en_cours":
            info(self, t("Ce voyage est déjà terminé."))
        else:
            self._run(CloseTripDialog(self, tid), "Retour camion gaz")

    def _tdays(self):
        tid = self._selected(self.ttable)
        if tid is None:
            info(self, t("Choisissez un voyage."))
        else:
            TripDaysDialog(self, tid).exec()
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
            self._run(DeliveryDialog(self, wid, self._day(), self._trip()), "Livraison gaz")

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
            self._open(gas_docs.build_day_sheet(self._day(), self._tmp(f"gaz_cahier_{part}.pdf"), self._trip(), part))

    def _print_statement(self):
        from app.printers import gas_docs

        wid = self._selected(self.wtable)
        if wid is None:
            info(self, t("Choisissez un grossiste."))
        else:
            self._open(gas_docs.build_wholesaler_statement(wid, self._tmp(f"gaz_releve_{wid}.pdf")))

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
            f"<b>{t('Dettes des grossistes')} :</b> {_money(f['debts'])} F &nbsp; <b>{t('Bénéfice')} :</b> {profit}<br><i>({inc})</i>")
        rows = gs.losses(start, end)
        self.losstable.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, val in enumerate([f"{r['date']:%d/%m/%Y}", r["line"], r["qty"], r["reason"]]):
                self.losstable.setItem(i, j, _cell(val, right=j == 2))

    def _lstd(self):
        n = gs.create_standard_lines()
        info(self, t("{n} produit(s) créé(s). Renseignez les prix.").format(n=n) if n else t("Les produits standard existent déjà."))
        self.refresh()

    def _fill_sources(self) -> None:
        current = self.source.currentData() if self.source.count() else None
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItem(t("Dépôt"), None)
        for tr in gs.list_trips(open_only=True):
            self.source.addItem(f"{t('Camion')} {tr.label}", tr.id)
        i = self.source.findData(current)
        self.source.setCurrentIndex(max(0, i))
        self.source.blockSignals(False)

    def refresh(self, *_a) -> None:
        if not getattr(self, "_filling", False):
            self._filling = True
            try:
                if self.sender() is not self.source:
                    self._fill_sources()
            finally:
                self._filling = False
        day = self._day()
        trip = self._trip()
        rows = gs.day_sheet(day, trip)
        self.sheet.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r["name"], r["si"], r["entry"], r["st"], r["sold"], _money(r["unit_price"]), _money(r["amount"]),
                    r["delivered"], r["lost"], r["sf"]]
            for j, val in enumerate(vals):
                self.sheet.setItem(i, j, _cell(val, right=j > 0))
        self.total_label.setText(f"<b>{t('Total du jour (détaillants)')} : {_money(gs.day_total(day, trip))} F</b>")
        ws = gs.list_wholesalers(False)
        self.wtable.setRowCount(len(ws))
        for i, w in enumerate(ws):
            a = gs.wholesaler_account(w.id)
            vals = [w.name, a.delivered, a.empties_back, _money(a.amount_due), _money(a.paid), _money(a.balance), a.statement]
            for j, val in enumerate(vals):
                self.wtable.setItem(i, j, _cell(val, right=0 < j < 6, data=w.id if j == 0 else None))
        ds = gs.deliveries_of_day(day, trip_id=trip)
        self.dtable.setRowCount(len(ds))
        for i, d in enumerate(ds):
            for j, val in enumerate([d["wholesaler"], sum(d["lines"].values()), d["empties_back"], _money(d["total"])]):
                self.dtable.setItem(i, j, _cell(val, right=j > 0))
        ts = gs.list_trips()
        self.ttable.setRowCount(len(ts))
        for i, tr in enumerate(ts):
            for j, val in enumerate([tr.number, tr.truck, tr.driver, f"{tr.started_at:%d/%m/%Y}", t("En cours") if tr.status == "en_cours" else t("Terminé"),
                                     tr.loaded, tr.remaining]):
                self.ttable.setItem(i, j, _cell(val, right=j >= 5, data=tr.id if j == 0 else None))
        self._refresh_states()
        ls = gs.list_lines(False)
        self.ltable.setRowCount(len(ls))
        for i, ln in enumerate(ls):
            cost = "—" if ln.cost_price is None else _money(ln.cost_price)
            for j, val in enumerate([ln.name, _money(ln.retail_price), _money(ln.wholesale_price), cost, ln.stock]):
                self.ltable.setItem(i, j, _cell(val, right=j > 0, data=ln.id if j == 0 else None))
