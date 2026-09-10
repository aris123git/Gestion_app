"""Dialogues d'ouverture et de fermeture de session de caisse."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services import settings_service
from app.services.cash_session_service import CashSessionService
from app.ui.widgets.helpers import info, warn
from app.utils.helpers import format_money


def _parse_non_negative_amount(text: str) -> Optional[float]:
    """Retourne le montant si la saisie est un nombre ≥ 0 (y compris 0 explicite)."""
    raw = (text or "").strip().replace(" ", "").replace(",", ".")
    if raw == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


class _ExplicitAmountField(QWidget):
    """Champ montant vide jusqu'à saisie ou clic sur « 0 ».

    Empêche de valider par inadvertance avec la valeur par défaut d'un spinbox.
    """

    def __init__(self, currency: str, parent=None):
        super().__init__(parent)
        self.currency = currency
        self._confirmed = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Saisir le montant…")
        self.input.setClearButtonEnabled(True)
        self.input.setAlignment(Qt.AlignmentFlag.AlignRight)
        validator = QDoubleValidator(0.0, 1_000_000_000.0, 0, self.input)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.input.setValidator(validator)
        self.input.textChanged.connect(self._on_text_changed)
        row.addWidget(self.input, 1)

        suffix = QLabel(currency)
        suffix.setStyleSheet("color: #64748b;")
        row.addWidget(suffix)

        self.zero_btn = QPushButton("0")
        self.zero_btn.setToolTip("Indiquer explicitement 0")
        self.zero_btn.setFixedWidth(48)
        self.zero_btn.setMinimumHeight(36)
        self.zero_btn.clicked.connect(self._set_zero)
        row.addWidget(self.zero_btn)

    def _on_text_changed(self, text: str) -> None:
        self._confirmed = _parse_non_negative_amount(text) is not None
        self.amountChanged()

    def _set_zero(self) -> None:
        self.input.setText("0")
        self.input.setFocus()
        self.input.selectAll()

    def amountChanged(self) -> None:
        """Hook surchargé / connecté par le parent via signal-like callback."""

    def set_on_change(self, callback) -> None:
        self.amountChanged = callback  # type: ignore[method-assign]

    def has_amount(self) -> bool:
        return self._confirmed and _parse_non_negative_amount(self.input.text()) is not None

    def amount(self) -> Optional[float]:
        if not self._confirmed:
            return None
        return _parse_non_negative_amount(self.input.text())


class OpenCashSessionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ouverture de caisse")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.opening_float: Optional[float] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        currency = settings_service.get_currency()
        layout.addWidget(
            QLabel(
                "Indiquez le <b>fond de caisse</b> (espèces déjà dans le tiroir) "
                "avant de commencer.<br/>"
                "<span style='color:#64748b;'>Saisissez un montant ou cliquez sur "
                "<b>0</b> si le tiroir est vide — obligatoire pour continuer.</span>"
            )
        )
        form = QFormLayout()
        self.amount_field = _ExplicitAmountField(currency)
        self.amount_field.set_on_change(self._refresh_ok)
        form.addRow("Fond de caisse", self.amount_field)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton("Ouvrir la caisse")
        self.ok.setObjectName("Primary")
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self._save)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.ok)
        layout.addLayout(buttons)
        self._refresh_ok()

    def _refresh_ok(self) -> None:
        self.ok.setEnabled(self.amount_field.has_amount())

    def _save(self) -> None:
        value = self.amount_field.amount()
        if value is None:
            warn(
                self,
                "Saisissez le fond de caisse ou cliquez sur 0 pour continuer.",
            )
            self.amount_field.input.setFocus()
            return
        self.opening_float = float(value)
        self.accept()


class CloseCashSessionDialog(QDialog):
    def __init__(self, session_id: int, expected: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fermeture de caisse")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.session_id = session_id
        self.expected = expected
        self.result_data: Optional[dict] = None
        currency = settings_service.get_currency()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(
            QLabel(
                f"Espèces attendues (fond + encaissements) : "
                f"<b>{format_money(expected, currency)}</b><br/>"
                "Comptez le tiroir et saisissez le montant trouvé.<br/>"
                "<span style='color:#64748b;'>Saisissez le montant compté ou cliquez "
                "sur <b>0</b> — obligatoire pour fermer (aucun montant prérempli).</span>"
            )
        )
        form = QFormLayout()
        self.counted_field = _ExplicitAmountField(currency)
        self.counted_field.set_on_change(self._on_counted_changed)
        self.note = QLineEdit()
        self.note.setPlaceholderText(
            "Commentaire (obligatoire si écart important)"
        )
        form.addRow("Montant compté", self.counted_field)
        form.addRow("Note", self.note)
        layout.addLayout(form)

        self.variance_label = QLabel(
            "<span style='color:#64748b;'>Écart : saisissez d'abord le montant compté</span>"
        )
        layout.addWidget(self.variance_label)

        buttons = QHBoxLayout()
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton("Fermer la caisse")
        self.ok.setObjectName("Danger")
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self._save)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.ok)
        layout.addLayout(buttons)
        self._refresh_ok()

    def _on_counted_changed(self) -> None:
        self._update_variance()
        self._refresh_ok()

    def _refresh_ok(self) -> None:
        self.ok.setEnabled(self.counted_field.has_amount())

    def _update_variance(self) -> None:
        currency = settings_service.get_currency()
        counted = self.counted_field.amount()
        if counted is None:
            self.variance_label.setText(
                "<span style='color:#64748b;'>Écart : saisissez d'abord "
                "le montant compté</span>"
            )
            return
        variance = float(counted) - self.expected
        color = "#16a34a" if abs(variance) < 0.01 else "#dc2626"
        self.variance_label.setText(
            f"<span style='color:{color};'>Écart : "
            f"{format_money(variance, currency)}</span>"
        )

    def _save(self) -> None:
        counted = self.counted_field.amount()
        if counted is None:
            warn(
                self,
                "Saisissez le montant compté ou cliquez sur 0 pour continuer.",
            )
            self.counted_field.input.setFocus()
            return
        note = self.note.text().strip()
        variance = abs(float(counted) - self.expected)
        from app.services.cash_controls import get_variance_note_threshold

        threshold = get_variance_note_threshold()
        if variance >= threshold + 0.009 and len(note) < 5:
            warn(
                self,
                f"Écart ≥ {threshold:g} : une note explicative est obligatoire "
                "(au moins 5 caractères).",
            )
            self.note.setFocus()
            return
        self.result_data = {
            "counted": float(counted),
            "note": note,
        }
        self.accept()


def ensure_cash_session_open(parent, state) -> bool:
    """Ouvre une session si absente. Retourne False si l'utilisateur refuse."""
    user = state.current_user
    if not user:
        return False
    open_sess = CashSessionService.get_open(user.id)
    if open_sess:
        return True
    dialog = OpenCashSessionDialog(parent=parent)
    if not dialog.exec() or dialog.opening_float is None:
        warn(parent, "La caisse doit être ouverte pour continuer.")
        return False
    try:
        CashSessionService.open_session(
            user.id,
            dialog.opening_float,
            username=getattr(user, "username", ""),
        )
    except ValueError as exc:
        warn(parent, str(exc))
        return False
    info(parent, "Caisse ouverte.")
    return True


def close_cash_session_flow(parent, state) -> bool:
    """Propose la fermeture de la session ouverte. True si fermée ou aucune."""
    user = state.current_user
    if not user:
        return True
    open_sess = CashSessionService.get_open(user.id)
    if not open_sess:
        return True
    expected = CashSessionService.compute_expected(open_sess.id)
    dialog = CloseCashSessionDialog(open_sess.id, expected, parent=parent)
    if not dialog.exec() or not dialog.result_data:
        return False
    try:
        closed = CashSessionService.close_session(
            open_sess.id,
            dialog.result_data["counted"],
            note=dialog.result_data["note"],
            user_id=user.id,
            username=getattr(user, "username", ""),
        )
    except ValueError as exc:
        warn(parent, str(exc))
        return False
    currency = settings_service.get_currency()
    info(
        parent,
        f"Caisse fermée.\n"
        f"Attendu : {format_money(closed.expected_cash, currency)}\n"
        f"Compté : {format_money(closed.closing_counted, currency)}\n"
        f"Écart : {format_money(closed.variance, currency)}",
    )
    return True
