"""Page des rapports : synthèse par période et exports PDF/Excel."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.controllers.report_controller import ReportController, period_bounds
from app.controllers.sale_controller import SaleController
from app.reports.excel_report import export_report_excel
from app.reports.pdf_report import export_report_pdf
from app.services import audit_service, settings_service
from app.ui.state import AppState
from app.ui.widgets.helpers import (
    confirm,
    info,
    make_card,
    page_title,
    section_title,
    warn,
)
from app.utils.helpers import format_datetime, format_money


class ReportsPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._report = None
        self._sale_ids: list[int] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(page_title("Rapports"))

        controls = QHBoxLayout()
        self.period = QComboBox()
        self.period.addItems(["Journalier", "Hebdomadaire", "Mensuel", "Annuel", "Personnalisé"])
        self.period.currentTextChanged.connect(self._period_changed)
        self.start = QDateEdit(QDate.currentDate())
        self.start.setCalendarPopup(True)
        self.end = QDateEdit(QDate.currentDate())
        self.end.setCalendarPopup(True)
        generate = QPushButton("Générer")
        generate.setObjectName("Primary")
        generate.clicked.connect(self._generate)
        controls.addWidget(QLabel("Période :"))
        controls.addWidget(self.period)
        controls.addWidget(QLabel("Du"))
        controls.addWidget(self.start)
        controls.addWidget(QLabel("Au"))
        controls.addWidget(self.end)
        controls.addWidget(generate)
        controls.addStretch()
        layout.addLayout(controls)
        self._period_changed(self.period.currentText())

        # Cartes de synthèse
        self.summary_grid = QGridLayout()
        self.summary_grid.setSpacing(12)
        self.lbl_revenue = self._metric("Chiffre d'affaires")
        self.lbl_sales = self._metric("Nombre de ventes")
        self.lbl_profit = self._metric("Bénéfice brut")
        self.lbl_expenses = self._metric("Dépenses")
        self.lbl_net = self._metric("Bénéfice net")
        for i, widget in enumerate(
            [self.lbl_revenue, self.lbl_sales, self.lbl_profit, self.lbl_expenses, self.lbl_net]
        ):
            self.summary_grid.addWidget(widget["card"], 0, i)
        layout.addLayout(self.summary_grid)

        layout.addWidget(section_title("Top produits sur la période"))
        self.top_table = QTableWidget(0, 3)
        self.top_table.setHorizontalHeaderLabels(["Produit", "Quantité", "Chiffre d'affaires"])
        self.top_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.top_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.top_table)

        # Historique détaillé des ventes (avec date et heure).
        layout.addWidget(section_title("Historique des ventes (date et heure)"))
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(
            ["Ticket", "Date et heure", "Caissier", "Paiement", "Total"]
        )
        self.history_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.history_table)

        # Annulation d'une vente : réservée à l'administrateur (remise en stock).
        history_actions = QHBoxLayout()
        history_actions.addStretch()
        self.cancel_sale_button = QPushButton("Annuler la vente sélectionnée")
        self.cancel_sale_button.setObjectName("Danger")
        self.cancel_sale_button.clicked.connect(self._cancel_selected_sale)
        history_actions.addWidget(self.cancel_sale_button)
        layout.addLayout(history_actions)

        exports = QHBoxLayout()
        exports.addStretch()
        pdf = QPushButton("Exporter PDF")
        pdf.clicked.connect(self._export_pdf)
        excel = QPushButton("Exporter Excel")
        excel.clicked.connect(self._export_excel)
        exports.addWidget(pdf)
        exports.addWidget(excel)
        layout.addLayout(exports)

    def _metric(self, title: str) -> dict:
        wrap = QWidget()
        inner = QVBoxLayout(wrap)
        inner.setContentsMargins(4, 4, 4, 4)
        caption = QLabel(title)
        caption.setStyleSheet("color: #64748b; font-size: 12px;")
        value = QLabel("—")
        value.setStyleSheet("font-size: 20px; font-weight: 700;")
        inner.addWidget(caption)
        inner.addWidget(value)
        return {"card": make_card(wrap), "value": value}

    def _period_changed(self, kind: str) -> None:
        # Les champs de date restent toujours modifiables : on peut donc choisir
        # librement le jour (ou la plage) à consulter, même avec un préréglage.
        self.start.setEnabled(True)
        self.end.setEnabled(True)
        if kind != "Personnalisé":
            start, end = period_bounds(kind)
            self.start.setDate(QDate(start.year, start.month, start.day))
            self.end.setDate(QDate(end.year, end.month, end.day))

    def _current_range(self):
        s = self.start.date()
        e = self.end.date()
        return date(s.year(), s.month(), s.day()), date(e.year(), e.month(), e.day())

    def _generate(self) -> None:
        start, end = self._current_range()
        self._report = ReportController.build(start, end)
        currency = settings_service.get_currency()
        self.lbl_revenue["value"].setText(format_money(self._report["revenue"], currency))
        self.lbl_sales["value"].setText(str(self._report["sales_count"]))
        self.lbl_profit["value"].setText(format_money(self._report["profit"], currency))
        self.lbl_expenses["value"].setText(format_money(self._report["expenses"], currency))
        self.lbl_net["value"].setText(format_money(self._report["net_profit"], currency))

        top = self._report["top_products"]
        self.top_table.setRowCount(len(top))
        for row, (name, qty, total) in enumerate(top):
            self.top_table.setItem(row, 0, QTableWidgetItem(name))
            self.top_table.setItem(row, 1, QTableWidgetItem(f"{qty:g}"))
            self.top_table.setItem(row, 2, QTableWidgetItem(format_money(total, currency)))

        # Historique des ventes de la période (le plus récent d'abord).
        sales = SaleController.list(start=start, end=end, limit=1000)
        self._sale_ids = [s.id for s in sales]
        self.history_table.setRowCount(len(sales))
        for row, sale in enumerate(sales):
            self.history_table.setItem(row, 0, QTableWidgetItem(sale.ticket_number))
            self.history_table.setItem(row, 1, QTableWidgetItem(format_datetime(sale.date)))
            self.history_table.setItem(row, 2, QTableWidgetItem(sale.cashier_name))
            self.history_table.setItem(row, 3, QTableWidgetItem(sale.payment_summary))
            total_item = QTableWidgetItem(format_money(sale.total, currency))
            if sale.status == "cancelled":
                total_item.setText(format_money(sale.total, currency) + " (annulée)")
            self.history_table.setItem(row, 4, total_item)

    def _cancel_selected_sale(self) -> None:
        """Annule la vente sélectionnée (admin uniquement) et remet en stock."""
        row = self.history_table.currentRow()
        if row < 0 or row >= len(self._sale_ids):
            warn(self, "Sélectionnez une vente dans l'historique.")
            return
        if not self.state.is_admin:
            warn(self, "Seul un administrateur peut annuler une vente.")
            return
        sale_id = self._sale_ids[row]
        ticket = self.history_table.item(row, 0)
        ticket_number = ticket.text() if ticket else str(sale_id)
        if not confirm(
            self,
            f"Annuler la vente {ticket_number} ?\n\n"
            "Les articles seront remis en stock et la vente ne comptera plus "
            "dans le chiffre d'affaires. Cette action est tracée dans le journal.",
        ):
            return
        SaleController.cancel_sale(sale_id, restock=True)
        audit_service.log_action(
            "Annulation vente", "Sale", ticket_number,
            self.state.user_id, getattr(self.state.current_user, "username", ""),
        )
        info(self, f"Vente {ticket_number} annulée et articles remis en stock.")
        self._generate()
        self.state.notify_data_changed()

    def refresh(self) -> None:
        self._generate()

    def _export_pdf(self) -> None:
        if not self._report:
            self._generate()
        path = export_report_pdf(self._report)
        info(self, f"Rapport PDF généré :\n{path}")

    def _export_excel(self) -> None:
        if not self._report:
            self._generate()
        start, end = self._current_range()
        rows = ReportController.sales_rows(start, end)
        path = export_report_excel(self._report, rows)
        info(self, f"Rapport Excel généré :\n{path}")
