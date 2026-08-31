"""Écran bureau multi-magasins : totaux, classement, détail."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services import enterprise_sync_service as sync
from app.services import settings_service
from app.ui.state import AppState
from app.ui.theme import PRIMARY, SUCCESS, WARNING
from app.ui.widgets.helpers import info, make_card, page_title, section_title, warn
from app.ui.widgets.stat_card import StatCard
from app.utils.helpers import format_money


class EnterprisePage(QWidget):
    """Vue consolidée des recettes de tous les magasins (Lot 1)."""

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._rows: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)
        root.addWidget(page_title("Réseau multi-magasins"))

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Jour :"))
        self.day = QDateEdit()
        self.day.setCalendarPopup(True)
        self.day.setDate(QDate.currentDate())
        self.day.dateChanged.connect(self.refresh)
        toolbar.addWidget(self.day)

        import_btn = QPushButton("Importer depuis le dossier partagé")
        import_btn.setObjectName("Primary")
        import_btn.clicked.connect(self._import)
        export_btn = QPushButton("Exporter ce magasin (aujourd'hui)")
        export_btn.clicked.connect(self._export)
        toolbar.addWidget(import_btn)
        toolbar.addWidget(export_btn)
        toolbar.addStretch()
        root.addLayout(toolbar)

        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        self.path_label.setStyleSheet("color: #64748b; font-size: 12px;")
        root.addWidget(self.path_label)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.card_revenue = StatCard("Recette totale", "0", PRIMARY, "💰")
        self.card_profit = StatCard("Bénéfice net", "0", SUCCESS, "📈")
        self.card_debts = StatCard("Dettes clients", "0", WARNING, "💳")
        self.card_shops = StatCard("Magasins", "0", "#475569", "🏪")
        for card in (
            self.card_revenue,
            self.card_profit,
            self.card_debts,
            self.card_shops,
        ):
            cards.addWidget(card)
        root.addLayout(cards)

        root.addWidget(section_title("Classement du jour (cliquer une ligne pour le détail)"))
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["#", "Code", "Magasin", "Recette", "Bénéfice net", "Dettes", "Ventes"]
        )
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.doubleClicked.connect(self._open_selected)
        root.addWidget(make_card(self.table), 1)

        detail_btn = QPushButton("Voir le détail du magasin sélectionné")
        detail_btn.clicked.connect(self._open_selected)
        root.addWidget(detail_btn)

    def _selected_day(self) -> date:
        qd = self.day.date()
        return date(qd.year(), qd.month(), qd.day())

    def _import(self) -> None:
        result = sync.scan_and_import()
        if result.ok:
            info(self, result.message, "Import")
        else:
            warn(self, result.message, "Import")
        self.refresh()

    def _export(self) -> None:
        result = sync.export_day_to_share(date.today())
        if result.ok:
            info(self, f"{result.message}\n\n{result.path}", "Export")
        else:
            warn(self, result.message, "Export")
        self.refresh()

    def refresh(self) -> None:
        day = self._selected_day()
        currency = settings_service.get_currency()
        folder = sync.share_directory()
        self.path_label.setText(f"Dossier partagé : {folder}")

        totals = sync.consolidated_for_day(day)
        self.card_revenue.set_value(format_money(totals["cash_revenue"], currency))
        self.card_profit.set_value(format_money(totals["profit_net"], currency))
        self.card_debts.set_value(format_money(totals["client_debts"], currency))
        self.card_shops.set_value(str(totals["shop_count"]))

        rows = sync.ranking_for_day(day)
        self._rows = rows
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = [
                str(index + 1),
                row.shop_code or "—",
                row.shop_name or row.shop_id,
                format_money(float(row.cash_revenue or 0), currency),
                format_money(float(row.profit_net or 0), currency),
                format_money(float(row.client_debts or 0), currency),
                str(int(row.sales_count or 0)),
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row.shop_id)
                if col >= 3:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.table.setItem(index, col, item)

    def _open_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            warn(self, "Sélectionnez un magasin dans le classement.", "Détail")
            return
        snap = self._rows[row]
        dialog = ShopDetailDialog(snap, self)
        dialog.exec()


class ShopDetailDialog(QDialog):
    """Détail d'un snapshot magasin pour le jour affiché."""

    def __init__(self, snap, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Détail — {snap.shop_name or snap.shop_code}")
        self.setModal(True)
        self.resize(420, 360)
        currency = snap.currency or settings_service.get_currency()

        layout = QVBoxLayout(self)
        layout.addWidget(page_title(snap.shop_name or snap.shop_code or "Magasin"))
        form = QFormLayout()
        form.addRow("Code", QLabel(snap.shop_code or "—"))
        form.addRow("Date", QLabel(snap.report_date.isoformat() if snap.report_date else "—"))
        form.addRow("Recette (CA)", QLabel(format_money(float(snap.cash_revenue or 0), currency)))
        form.addRow(
            "Bénéfice brut",
            QLabel(format_money(float(snap.profit_gross or 0), currency)),
        )
        form.addRow(
            "Bénéfice net",
            QLabel(format_money(float(snap.profit_net or 0), currency)),
        )
        form.addRow("Dépenses", QLabel(format_money(float(snap.expenses or 0), currency)))
        form.addRow("Ventes", QLabel(str(int(snap.sales_count or 0))))
        form.addRow(
            "Dettes clients",
            QLabel(
                f"{format_money(float(snap.client_debts or 0), currency)} "
                f"({int(snap.client_debts_count or 0)} dossier(s))"
            ),
        )
        form.addRow(
            "Règlements dettes",
            QLabel(format_money(float(snap.debt_repayments or 0), currency)),
        )
        form.addRow("Trésorerie", QLabel(format_money(float(snap.treasury or 0), currency)))
        layout.addLayout(form)
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
