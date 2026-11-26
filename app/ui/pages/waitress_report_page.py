"""Rapport serveuses — Maquis Caisse PC : ventes/encaissements et
commission (ou pourboire) par serveuse sur une période donnée."""

from __future__ import annotations

from PySide6.QtWidgets import QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from app.i18n import t
from app.services import settings_service
from app.ui.widgets.helpers import page_title
from app.utils.helpers import format_money


class WaitressReportPage(QWidget):
    """Liste, par serveuse, les commandes/CA généré/encaissé et la commission
    (calculée depuis le taux défini sur chaque serveuse dans Utilisateurs)."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._period_bar = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        self.title = page_title(t("Rapport serveuses"))
        layout.addWidget(self.title)
        self._page_layout = layout
        self.hint = QLabel(
            t(
                "Ventes/encaissements et commission (ou pourboire) par serveuse. "
                "Le taux de commission se règle par serveuse dans Utilisateurs."
            )
        )
        self.hint.setStyleSheet("color: #64748b;")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [
                t("Serveuse"),
                t("Commandes"),
                t("CA généré"),
                t("CA encaissé"),
                t("À encaisser"),
                t("Commission / pourboire"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        self.total_label = QLabel()
        self.total_label.setStyleSheet("font-weight: 700;")
        layout.addWidget(self.total_label)
        self._ensure_period_bar()
        self.refresh()

    def _ensure_period_bar(self) -> None:
        if self._period_bar is not None:
            return
        from app.ui.widgets.maquis_period_bar import MaquisPeriodBar

        self._period_bar = MaquisPeriodBar(self)
        self._period_bar.period_changed.connect(lambda _sel: self.refresh())
        self._page_layout.insertWidget(1, self._period_bar)

    def refresh(self) -> None:
        from app.services.maquis_dashboard_service import waitress_commission_report

        self._ensure_period_bar()
        selection = self._period_bar.selection()
        start, end = selection.bounds()
        currency = settings_service.get_currency()
        self.title.setText(f"{t('Rapport serveuses')} — {selection.period.label}")
        rows = waitress_commission_report(start=start, end=end)
        self.table.setRowCount(len(rows))
        total_commission = 0.0
        for row, w in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(w.waitress_name))
            self.table.setItem(row, 1, QTableWidgetItem(str(w.order_count)))
            self.table.setItem(row, 2, QTableWidgetItem(format_money(w.ca_generated, currency)))
            self.table.setItem(row, 3, QTableWidgetItem(format_money(w.ca_collected, currency)))
            self.table.setItem(row, 4, QTableWidgetItem(format_money(w.to_collect, currency)))
            label = format_money(w.commission_amount, currency)
            if w.commission_rate:
                label = f"{label} ({w.commission_rate:g} %)"
            self.table.setItem(row, 5, QTableWidgetItem(label))
            total_commission += w.commission_amount
        self.total_label.setText(
            f"{t('Total commissions / pourboires')} : {format_money(total_commission, currency)}"
        )
