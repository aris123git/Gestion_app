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
from app.services import permissions as perms, settings_service
from app.services.dashboard_service import DashboardService
from app.services.inventory_service import InventoryService
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
        self.card_treasury = StatCard("Trésorerie (jour)", "0", "#0f766e", "🏦")
        self.card_client_debts = StatCard("Dettes clients", "0", "#b45309", "👤")
        self.card_supplier_debts = StatCard("Dettes fournisseurs", "0", "#7c2d12", "🚚")
        self.card_net = StatCard("Bénéfice net", "0", "#4c1d95", "💹")

        cards = [
            self.card_revenue_today,
            self.card_revenue_month,
            self.card_sales,
            self.card_profit,
            self.card_net,
            self.card_expenses,
            self.card_treasury,
            self.card_client_debts,
            self.card_supplier_debts,
            self.card_low,
            self.card_out,
            self.card_products,
        ]
        for index, card in enumerate(cards):
            grid.addWidget(card, index // 4, index % 4)
        layout.addLayout(grid)
        self._cards_grid = grid

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
        alert_layout.addWidget(section_title("Alertes de stock / prévisions"))
        self.alert_table = QTableWidget(0, 4)
        self.alert_table.setHorizontalHeaderLabels(
            ["Produit", "Stock", "Seuil", "Rupture estimée"]
        )
        self.alert_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.alert_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        alert_layout.addWidget(self.alert_table)
        lists.addWidget(make_card(alert_wrap))

        layout.addLayout(lists)

        self.insights = section_title("Insights")
        layout.addWidget(self.insights)
        self.insights_label = QLabel("")
        self.insights_label.setWordWrap(True)
        layout.addWidget(self.insights_label)
        layout.addStretch()
        self._apply_permissions()

    def _apply_permissions(self) -> None:
        show_profits = self.state.can(perms.VIEW_PROFITS)
        self.card_profit.setVisible(show_profits)
        self.card_expenses.setVisible(show_profits)
        self.card_treasury.setVisible(show_profits)
        self.card_client_debts.setVisible(show_profits)
        self.card_supplier_debts.setVisible(show_profits)
        self.card_net.setVisible(show_profits)
        self.insights.setVisible(show_profits)
        self.insights_label.setVisible(show_profits)

    def refresh(self) -> None:
        self._apply_permissions()
        currency = settings_service.get_currency()
        data = DashboardController.summary()
        fin = DashboardService.financial_summary()
        self.card_revenue_today.set_value(format_money(data["revenue_today"], currency))
        self.card_revenue_month.set_value(format_money(data["revenue_month"], currency))
        self.card_sales.set_value(str(data["sales_today"]))
        if self.state.can(perms.VIEW_PROFITS):
            self.card_profit.set_value(format_money(data["profit_today"], currency))
            self.card_expenses.set_value(format_money(data["expenses_today"], currency))
            self.card_treasury.set_value(format_money(fin["treasury"], currency))
            self.card_client_debts.set_value(
                format_money(fin["client_debts"], currency)
            )
            self.card_supplier_debts.set_value(
                format_money(fin["supplier_debts"], currency)
            )
            self.card_net.set_value(format_money(fin["profit_net_today"], currency))
            best = DashboardService.best_clients_periods()
            top_qty = DashboardService.top_product_by_qty()
            top_profit = DashboardService.top_product_by_profit()
            dormant = DashboardService.dormant_products(limit=3)
            lines = []
            for label, key in (
                ("jour", "day"),
                ("semaine", "week"),
                ("mois", "month"),
                ("année", "year"),
            ):
                item = best.get(key)
                if item:
                    lines.append(
                        f"Meilleur client ({label}) : {item[0]} "
                        f"({format_money(item[1], currency)})"
                    )
            if top_qty:
                lines.append(f"Produit le plus vendu : {top_qty[0]} ({top_qty[1]:g})")
            if top_profit:
                lines.append(
                    f"Produit le plus rentable : {top_profit[0]} "
                    f"({format_money(top_profit[1], currency)})"
                )
            if dormant:
                names = ", ".join(n for n, _ in dormant)
                lines.append(f"Produits dormants : {names}")
            self.insights_label.setText("\n".join(lines) or "Pas encore assez de données.")
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
            forecast = InventoryService.stockout_forecast(product.id)
            days = forecast.get("days_left")
            eta = "—" if days is None else f"{days} j"
            self.alert_table.setItem(row, 0, QTableWidgetItem(product.name))
            self.alert_table.setItem(
                row, 1, QTableWidgetItem(format_quantity(product.quantity))
            )
            self.alert_table.setItem(
                row, 2, QTableWidgetItem(format_quantity(product.min_stock))
            )
            self.alert_table.setItem(row, 3, QTableWidgetItem(eta))
