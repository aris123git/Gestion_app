"""Dialogues d'ouverture et de fermeture de session de caisse."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.services import settings_service
from app.services.cash_session_service import CashSessionService
from app.ui.widgets.helpers import info, warn
from app.utils.helpers import format_money


class OpenCashSessionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ouverture de caisse")
        self.setModal(True)
        self.setMinimumWidth(400)
        self.opening_float: Optional[float] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        currency = settings_service.get_currency()
        layout.addWidget(
            QLabel(
                "Indiquez le <b>fond de caisse</b> (espèces déjà dans le tiroir) "
                "avant de commencer."
            )
        )
        form = QFormLayout()
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1_000_000_000)
        self.amount.setDecimals(0)
        self.amount.setSuffix(f" {currency}")
        form.addRow("Fond de caisse", self.amount)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        ok = QPushButton("Ouvrir la caisse")
        ok.setObjectName("Primary")
        ok.clicked.connect(self._save)
        buttons.addStretch()
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def _save(self) -> None:
        self.opening_float = float(self.amount.value())
        self.accept()


class CloseCashSessionDialog(QDialog):
    def __init__(self, session_id: int, expected: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fermeture de caisse")
        self.setModal(True)
        self.setMinimumWidth(440)
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
                "Comptez le tiroir et saisissez le montant trouvé."
            )
        )
        form = QFormLayout()
        self.counted = QDoubleSpinBox()
        self.counted.setRange(0, 1_000_000_000)
        self.counted.setDecimals(0)
        self.counted.setValue(expected)
        self.counted.setSuffix(f" {currency}")
        self.note = QLineEdit()
        self.note.setPlaceholderText("Commentaire (facultatif)")
        form.addRow("Montant compté", self.counted)
        form.addRow("Note", self.note)
        layout.addLayout(form)

        self.variance_label = QLabel("")
        layout.addWidget(self.variance_label)
        self.counted.valueChanged.connect(self._update_variance)
        self._update_variance()

        buttons = QHBoxLayout()
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Fermer la caisse")
        ok.setObjectName("Danger")
        ok.clicked.connect(self._save)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def _update_variance(self) -> None:
        currency = settings_service.get_currency()
        variance = float(self.counted.value()) - self.expected
        color = "#16a34a" if abs(variance) < 0.01 else "#dc2626"
        self.variance_label.setText(
            f"<span style='color:{color};'>Écart : "
            f"{format_money(variance, currency)}</span>"
        )

    def _save(self) -> None:
        self.result_data = {
            "counted": float(self.counted.value()),
            "note": self.note.text().strip(),
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
