"""Tableau de bord : indicateurs clés et listes d'alerte."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.controllers.dashboard_controller import DashboardController
from app.controllers.product_controller import ProductController
from app.services import settings_service
from app.ui.state import AppState
from app.ui.theme import DANGER, PRIMARY, SUCCESS, WARNING
from app.ui.widgets.helpers import make_card, page_title, section_title
from app.ui.widgets.stat_card import StatCard
from app.utils.helpers import format_money, format_quantity


class DashboardPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        scroll.setWidget(container)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        self.title = page_title("Tableau de bord")
        layout.addWidget(self.title)

        # --- Cartes d'indicateurs -----------------------------------------
        grid = QGridLayout()
        grid.setSpacing(16)
        self.card_revenue_today = StatCard("CA du jour", "0", PRIMARY, "💰")
        self.card_revenue_month = StatCard("CA du mois", "0", "#0891b2", "📅")
        self.card_sales = StatCard("Ventes du jour", "0", SUCCESS, "🧾")
        self.card_profit = StatCard("Bénéfice estimé", "0", "#7c3aed", "📈")
        self.card_expenses = StatCard("Dépenses du jour", "0", WARNING, "💸")
        self.card_low = StatCard("Stock faible", "0", "#ea580c", "⚠️")
        self.card_out = StatCard("Ruptures", "0", DANGER, "⛔")
        self.card_products = StatCard("Produits", "0", "#475569", "📦")

        cards = [
            self.card_revenue_today,
            self.card_revenue_month,
            self.card_sales,
            self.card_profit,
            self.card_expenses,
            self.card_low,
            self.card_out,
            self.card_products,
        ]
        for index, card in enumerate(cards):
            grid.addWidget(card, index // 4, index % 4)
        layout.addLayout(grid)

        # --- Listes : top produits + alertes ------------------------------
        lists = QHBoxLayout()
        lists.setSpacing(16)

        top_wrap = QWidget()
        top_layout = QVBoxLayout(top_wrap)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(section_title("Produits les plus vendus (30 j)"))
        self.top_table = QTableWidget(0, 3)
        self.top_table.setHorizontalHeaderLabels(["Produit", "Quantité", "CA"])
        self.top_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.top_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        top_layout.addWidget(self.top_table)
        lists.addWidget(make_card(top_wrap))

        alert_wrap = QWidget()
        alert_layout = QVBoxLayout(alert_wrap)
        alert_layout.setContentsMargins(0, 0, 0, 0)
        alert_layout.addWidget(section_title("Alertes de stock"))
        self.alert_table = QTableWidget(0, 3)
        self.alert_table.setHorizontalHeaderLabels(["Produit", "Stock", "Seuil"])
        self.alert_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.alert_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        alert_layout.addWidget(self.alert_table)
        lists.addWidget(make_card(alert_wrap))

        layout.addLayout(lists)
        layout.addStretch()

    def refresh(self) -> None:
        currency = settings_service.get_currency()
        data = DashboardController.summary()
        self.card_revenue_today.set_value(format_money(data["revenue_today"], currency))
        self.card_revenue_month.set_value(format_money(data["revenue_month"], currency))
        self.card_sales.set_value(str(data["sales_today"]))
        self.card_profit.set_value(format_money(data["profit_today"], currency))
        self.card_expenses.set_value(format_money(data["expenses_today"], currency))
        self.card_low.set_value(str(data["low_stock"]))
        self.card_out.set_value(str(data["out_of_stock"]))
        self.card_products.set_value(str(data["total_products"]))

        top = DashboardController.top_products(limit=8)
        self.top_table.setRowCount(len(top))
        for row, (name, qty, total) in enumerate(top):
            self.top_table.setItem(row, 0, QTableWidgetItem(name))
            self.top_table.setItem(row, 1, QTableWidgetItem(format_quantity(qty)))
            self.top_table.setItem(row, 2, QTableWidgetItem(format_money(total, currency)))

        alerts = ProductController.low_stock(limit=50)
        self.alert_table.setRowCount(len(alerts))
        for row, product in enumerate(alerts):
            self.alert_table.setItem(row, 0, QTableWidgetItem(product.name))
            self.alert_table.setItem(
                row, 1, QTableWidgetItem(format_quantity(product.quantity))
            )
            self.alert_table.setItem(
                row, 2, QTableWidgetItem(format_quantity(product.min_stock))
            )
