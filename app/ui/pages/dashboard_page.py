"""Tableau de bord : indicateurs clés et listes d'alerte."""
from __future__ import annotations
from app.i18n import t
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from app.controllers.dashboard_controller import DashboardController
from app.controllers.product_controller import ProductController
from app.services import permissions as perms, product_profile, settings_service
from app.services.dashboard_service import DashboardService
from app.services.inventory_service import InventoryService
from app.ui.state import AppState
from app.ui.responsive import LayoutProfile
from app.ui.theme import DANGER, PRIMARY, SUCCESS, WARNING
from app.ui.widgets.helpers import make_card, page_title, section_title
from app.ui.widgets.mini_charts import MultiLineChart
from app.ui.widgets.stat_card import StatCard
from app.utils.helpers import format_money, format_quantity

NET_PROFIT_COLOR = '#7c3aed'


def _delta_hint(now: float, before: float) -> str:
    """Texte court de variation vs la veille, vide si rien de comparable."""
    if not before:
        return ''
    pct = (now - before) / before * 100
    sign = '+' if pct >= 0 else ''
    return f"{sign}{pct:.0f} % vs hier"


def _urgency_colors(days_left) -> tuple[str, str]:
    if days_left is None:
        return ('#f1f5f9', '#64748b')
    if days_left <= 3:
        return ('#fee2e2', '#991b1b')
    if days_left <= 7:
        return ('#fef3c7', '#92400e')
    return ('#f1f5f9', '#64748b')


class _StockHealthCard(QFrame):
    """Carte compacte regroupant ruptures, stock faible et nombre de produits."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName('Card')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(28)
        self._out = self._segment(DANGER)
        self._low = self._segment('#ea580c')
        self._total = self._segment('#475569')
        for box, _value, _caption in (self._out, self._low, self._total):
            layout.addLayout(box)
        layout.addStretch(1)

    @staticmethod
    def _segment(color: str):
        box = QVBoxLayout()
        box.setSpacing(2)
        value = QLabel('0')
        value.setStyleSheet(f'font-size: 20px; font-weight: 700; color: {color};')
        caption = QLabel('')
        caption.setStyleSheet('font-size: 11.5px; color: #64748b;')
        box.addWidget(value)
        box.addWidget(caption)
        return box, value, caption

    def set_values(self, out_of_stock: int, low_stock: int, total_products: int) -> None:
        self._out[1].setText(str(out_of_stock))
        self._out[2].setText(t('Ruptures'))
        self._low[1].setText(str(low_stock))
        self._low[2].setText(t('Stock faible'))
        self._total[1].setText(str(total_products))
        self._total[2].setText(t('Produits'))


def _legend_label(color: str, text: str) -> QLabel:
    label = QLabel(f"<span style='color:{color}'>●</span> {text}")
    label.setStyleSheet('font-size: 12px; color: #64748b;')
    return label


def _chip(text: str) -> QLabel:
    chip = QLabel(text)
    chip.setWordWrap(True)
    chip.setStyleSheet(
        'background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; '
        'padding: 7px 12px; font-size: 12.5px; color: #334155;'
    )
    return chip


class DashboardPage(QWidget):

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._maquis = product_profile.is_maquis()
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
        self._page_layout = layout
        self.title = page_title(t('Tableau de bord'))
        layout.addWidget(self.title)

        self.card_revenue_today = StatCard('CA encaissé jour', '0', PRIMARY, '💰')
        self.card_revenue_month = StatCard('CA encaissé mois', '0', '#0891b2', '📅')
        self.card_sales = StatCard('Ventes du jour', '0', SUCCESS, '🧾')
        self.card_profit = StatCard('Bénéfice estimé ventes', '0', '#7c3aed', '📈')
        self.card_expenses = StatCard('Dépenses du jour', '0', WARNING, '💸')
        self.card_low = StatCard('Stock faible', '0', '#ea580c', '⚠️')
        self.card_out = StatCard('Ruptures', '0', DANGER, '⛔')
        self.card_products = StatCard('Produits', '0', '#475569', '📦')
        self.card_treasury = StatCard('Trésorerie (jour)', '0', '#0f766e', '🏦')
        self.card_net = StatCard('Bénéfice net après dépenses', '0', NET_PROFIT_COLOR, '💹')
        self.card_debt = StatCard('Dette total', '0', '#b45309', '💳', hint='Cliquer pour le détail', on_click=self._open_debts)
        self._cards = [self.card_revenue_today, self.card_revenue_month, self.card_sales, self.card_profit, self.card_net, self.card_expenses, self.card_treasury, self.card_debt, self.card_low, self.card_out, self.card_products]

        self._chart_card = None
        self._chart = None
        self._stock_health = None
        self._insights_card = None
        self._insights_grid = None
        self._cards_grid = None

        if not self._maquis:
            # Ces cartes ne servent qu'au tableau de bord Maquis (relabellisées) :
            # on les garde pour cette logique mais on ne les affiche pas ici.
            for card in (self.card_profit, self.card_expenses, self.card_low, self.card_out, self.card_products):
                card.setParent(self)
                card.hide()

        if self._maquis:
            grid = QGridLayout()
            grid.setSpacing(16)
            for index, card in enumerate(self._cards):
                grid.addWidget(card, index // 4, index % 4)
            layout.addLayout(grid)
            self._cards_grid = grid
        else:
            hero = QHBoxLayout()
            hero.setSpacing(16)
            for card in (self.card_revenue_today, self.card_sales, self.card_net, self.card_treasury):
                hero.addWidget(card)
            layout.addLayout(hero)
            self._hero_row = hero

            chart_box = QWidget()
            chart_layout = QVBoxLayout(chart_box)
            chart_layout.setContentsMargins(0, 0, 0, 0)
            chart_layout.setSpacing(6)
            head = QHBoxLayout()
            head.addWidget(section_title(t('CA et bénéfice — 14 derniers jours')))
            head.addStretch(1)
            head.addWidget(_legend_label(PRIMARY, t('CA encaissé')))
            head.addWidget(_legend_label(NET_PROFIT_COLOR, t('Bénéfice net')))
            chart_layout.addLayout(head)
            self._chart = MultiLineChart()
            chart_layout.addWidget(self._chart)
            self._chart_card = make_card(chart_box)
            layout.addWidget(self._chart_card)

            second = QHBoxLayout()
            second.setSpacing(16)
            self._stock_health = _StockHealthCard()
            second.addWidget(self._stock_health, 2)
            second.addWidget(self.card_revenue_month, 1)
            second.addWidget(self.card_debt, 1)
            layout.addLayout(second)
            self._second_row = second

        lists = QHBoxLayout()
        lists.setSpacing(16)
        self._lists_layout = lists
        top_wrap = QWidget()
        top_layout = QVBoxLayout(top_wrap)
        top_layout.setContentsMargins(0, 0, 0, 0)
        self._top_section = section_title(t('Produits les plus vendus (30 j)'))
        top_layout.addWidget(self._top_section)
        self.top_table = QTableWidget(0, 3)
        self.top_table.setHorizontalHeaderLabels([t('Produit'), t('Quantité'), t('Total ventes')])
        self.top_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.top_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        top_layout.addWidget(self.top_table)
        self._top_card = make_card(top_wrap)
        lists.addWidget(self._top_card)
        alert_wrap = QWidget()
        alert_layout = QVBoxLayout(alert_wrap)
        alert_layout.setContentsMargins(0, 0, 0, 0)
        self._alert_section = section_title(t('Alertes de stock / prévisions'))
        alert_layout.addWidget(self._alert_section)
        self.alert_table = QTableWidget(0, 4)
        self.alert_table.setHorizontalHeaderLabels([t('Produit'), t('Stock'), t('Seuil'), t('Rupture estimée')])
        self.alert_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.alert_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        alert_layout.addWidget(self.alert_table)
        self._alert_card = make_card(alert_wrap)
        lists.addWidget(self._alert_card)
        layout.addLayout(lists)

        if self._maquis:
            self.insights = section_title(t('Insights'))
            layout.addWidget(self.insights)
            self.insights_label = QLabel('')
            self.insights_label.setWordWrap(True)
            layout.addWidget(self.insights_label)
        else:
            insights_box = QWidget()
            insights_layout = QVBoxLayout(insights_box)
            insights_layout.setContentsMargins(0, 0, 0, 0)
            insights_layout.setSpacing(10)
            insights_layout.addWidget(section_title(t('Insights')))
            grid = QGridLayout()
            grid.setSpacing(8)
            insights_layout.addLayout(grid)
            self._insights_grid = grid
            self._insights_card = make_card(insights_box)
            layout.addWidget(self._insights_card)

        layout.addStretch()
        self._maquis_period_bar = None
        self._apply_permissions()
        self.state.layout_changed.connect(self._on_layout_changed)
        if self.state.layout is not None:
            self._on_layout_changed(self.state.layout)

    def _reflow_cards(self, columns: int) -> None:
        cols = max(1, int(columns))
        visible_cards = [c for c in self._cards if c.isVisible()]
        for card in self._cards:
            self._cards_grid.removeWidget(card)
        for index, card in enumerate(visible_cards):
            self._cards_grid.addWidget(card, index // cols, index % cols)

    def _set_insight_chips(self, lines: list[str]) -> None:
        grid = self._insights_grid
        while grid.count():
            item = grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for index, text in enumerate(lines):
            grid.addWidget(_chip(text), index // 2, index % 2)
        self._insights_card.setVisible(bool(lines))

    def _on_layout_changed(self, profile: LayoutProfile) -> None:
        margins = 12 if profile.density == 'compact' else 24
        spacing = 10 if profile.is_short else 18
        self._page_layout.setContentsMargins(margins, margins, margins, margins)
        self._page_layout.setSpacing(spacing)
        mobile = profile.width_mode == 'mobile'
        if self._maquis:
            self._reflow_cards(profile.card_columns)
            self._cards_grid.setSpacing(8 if profile.is_short else 16)
        else:
            self._hero_row.setDirection(QHBoxLayout.Direction.TopToBottom if mobile else QHBoxLayout.Direction.LeftToRight)
            self._second_row.setDirection(QHBoxLayout.Direction.TopToBottom if mobile else QHBoxLayout.Direction.LeftToRight)
        self._lists_layout.setDirection(QHBoxLayout.Direction.TopToBottom if mobile else QHBoxLayout.Direction.LeftToRight)
        for card in self._cards:
            card.setMinimumHeight(72 if profile.density == 'compact' else 120)

    def _ensure_maquis_period_bar(self) -> None:
        if self._maquis_period_bar is not None:
            return
        from app.ui.widgets.maquis_period_bar import MaquisPeriodBar

        self._maquis_period_bar = MaquisPeriodBar(self)
        self._maquis_period_bar.period_changed.connect(lambda _sel: self._refresh_maquis())
        self._page_layout.insertWidget(1, self._maquis_period_bar)

    def _refresh_maquis(self) -> None:
        from app.services.maquis_dashboard_service import dashboard_stats

        self._ensure_maquis_period_bar()
        selection = self._maquis_period_bar.selection()
        start, end = selection.bounds()
        period_label = selection.period.label
        currency = settings_service.get_currency()
        uid = getattr(self.state, "user_id", None)
        day = dashboard_stats(start=start, end=end, user_id=uid)
        self.title.setText(f"{t('Tableau de bord')} — {period_label}")
        self.card_revenue_today.set_title(t("CA généré"))
        self.card_revenue_today.set_value(format_money(day.ca_generated, currency))
        self.card_revenue_month.set_title(t("CA encaissé"))
        self.card_revenue_month.set_value(format_money(day.ca_collected, currency))
        self.card_sales.set_title(t("Commandes"))
        self.card_sales.set_value(str(day.orders_count))
        self.card_profit.set_title(t("Bénéfice"))
        profit_hint = f" ({day.margin_percent} %)" if day.margin_percent else ""
        self.card_profit.set_value(format_money(day.benefice, currency) + profit_hint)
        self.card_expenses.set_title(t("Dépenses"))
        self.card_expenses.set_value(format_money(day.expenses_total, currency))
        self.card_treasury.set_title(t("À encaisser"))
        self.card_treasury.set_value(format_money(day.to_collect, currency))
        self.card_net.set_title(t("Commandes ouvertes"))
        self.card_net.set_value(str(day.open_orders))
        self.card_low.set_title(t("Espèces"))
        self.card_low.set_value(format_money(day.caisse_du_jour.cash_today, currency))
        self.card_out.set_title(t("Mobile"))
        self.card_out.set_value(format_money(day.caisse_du_jour.mobile_today, currency))
        self.card_products.set_title(t("Dettes créées"))
        self.card_products.set_value(format_money(day.caisse_du_jour.debt_today, currency))
        if day.caisse_du_jour.especes_theoriques is not None:
            self.card_debt.set_title(t("Espèces théoriques"))
            self.card_debt.set_value(
                format_money(day.caisse_du_jour.especes_theoriques, currency)
            )
            hint = ""
            if day.caisse_du_jour.ecart is not None:
                hint = f"Écart : {format_money(day.caisse_du_jour.ecart, currency)}"
            self.card_debt.set_hint(hint or t("Session caisse ouverte"))
        if hasattr(self, "_top_section"):
            self._top_section.setText(t("Serveuses"))
        if hasattr(self, "_alert_section"):
            self._alert_section.setText(t("Top produits (commandes payées)"))
        self.top_table.setHorizontalHeaderLabels(
            [t("Serveuse"), t("Commandes"), t("CA généré"), t("À encaisser")]
        )
        ws = day.waitress_stats
        self.top_table.setRowCount(len(ws))
        for row, w in enumerate(ws):
            self.top_table.setItem(row, 0, QTableWidgetItem(w.waitress_name))
            self.top_table.setItem(row, 1, QTableWidgetItem(str(w.order_count)))
            self.top_table.setItem(
                row, 2, QTableWidgetItem(format_money(w.ca_generated, currency))
            )
            self.top_table.setItem(
                row, 3, QTableWidgetItem(format_money(w.to_collect, currency))
            )
        prods = day.top_products
        self.alert_table.setHorizontalHeaderLabels(
            [t("Produit"), t("Qté"), t("CA"), t("Marge")]
        )
        self.alert_table.setRowCount(len(prods))
        for row, p in enumerate(prods):
            self.alert_table.setItem(row, 0, QTableWidgetItem(p.product_name))
            self.alert_table.setItem(row, 1, QTableWidgetItem(format_quantity(p.quantity)))
            self.alert_table.setItem(row, 2, QTableWidgetItem(format_money(p.revenue, currency)))
            self.alert_table.setItem(
                row, 3, QTableWidgetItem(format_money(p.benefice, currency))
            )
        lines = [
            f"{t('Coût marchandises')} : {format_money(day.cost_of_goods, currency)}",
            f"{t('CA encaissé')} : {format_money(day.ca_collected, currency)}",
            f"{t('Règlements dettes')} : {format_money(day.repayment_revenue, currency)}",
        ]
        if day.caisse_du_jour.fond_de_caisse is not None:
            lines.append(
                f"{t('Fond de caisse')} : {format_money(day.caisse_du_jour.fond_de_caisse, currency)}"
            )
        self.insights_label.setText("\n".join(lines))

    def _open_debts(self) -> None:
        """Ouvre la page Dettes (onglet non payées) depuis la carte Dette total."""
        window = self.window()
        if window is None or not hasattr(window, '_select_page_by_label'):
            return
        page = window._select_page_by_label(t('nav.clients'))
        if page is not None and hasattr(page, 'show_unpaid'):
            page.show_unpaid()

    def _apply_permissions(self) -> None:
        show_profits = self.state.can(perms.VIEW_PROFITS)
        show_debts = self.state.can(perms.MANAGE_CLIENT_DEBTS)
        if self._maquis:
            self.card_profit.setVisible(show_profits)
            self.card_expenses.setVisible(show_profits)
            self.card_treasury.setVisible(show_profits)
            self.card_net.setVisible(show_profits)
            self.insights.setVisible(show_profits)
            self.insights_label.setVisible(show_profits)
            self.card_debt.setVisible(show_debts)
            if self.state.layout is not None:
                self._reflow_cards(self.state.layout.card_columns)
        else:
            self.card_net.setVisible(show_profits)
            self.card_treasury.setVisible(show_profits)
            self._chart_card.setVisible(show_profits)
            if self._insights_card is not None:
                self._insights_card.setVisible(show_profits)
            self.card_debt.setVisible(show_debts)

    def refresh(self) -> None:
        self._apply_permissions()

        if self._maquis:
            self._refresh_maquis()
            return
        currency = settings_service.get_currency()
        data = DashboardController.summary()
        fin = DashboardService.financial_summary()
        self.card_revenue_today.set_value(format_money(data['revenue_today'], currency))
        self.card_revenue_month.set_value(format_money(data['revenue_month'], currency))
        self.card_sales.set_value(str(data['sales_today']))
        show_profits = self.state.can(perms.VIEW_PROFITS)
        if show_profits:
            trend = DashboardService.daily_trend(days=14)
            yesterday_revenue = trend['revenue'][-2] if len(trend['revenue']) >= 2 else 0
            yesterday_profit = trend['net_profit'][-2] if len(trend['net_profit']) >= 2 else 0
            self.card_revenue_today.set_hint(_delta_hint(data['revenue_today'], yesterday_revenue))
            net_today = fin['profit_net_today']
            self.card_net.set_value(format_money(net_today, currency))
            self.card_net.set_hint(_delta_hint(net_today, yesterday_profit))
            self.card_treasury.set_value(format_money(fin['treasury'], currency))
            self._chart.set_series(trend['labels'], [
                (t('CA encaissé'), PRIMARY, trend['revenue']),
                (t('Bénéfice net'), NET_PROFIT_COLOR, trend['net_profit']),
            ])
            best = DashboardService.best_clients_periods()
            top_qty = DashboardService.top_product_by_qty()
            top_profit = DashboardService.top_product_by_profit()
            dormant = DashboardService.dormant_products(limit=3)
            lines = []
            for label, key in (('jour', 'day'), ('semaine', 'week'), ('mois', 'month'), ('année', 'year')):
                item = best.get(key)
                if item:
                    lines.append(f'🏆 Meilleur client ({label}) : {item[0]} ({format_money(item[1], currency)})')
            if top_qty:
                lines.append(f'📦 Produit le plus vendu : {top_qty[0]} ({top_qty[1]:g})')
            if top_profit:
                lines.append(f'💹 Produit le plus rentable : {top_profit[0]} ({format_money(top_profit[1], currency)})')
            if dormant:
                names = ', '.join((n for n, _ in dormant))
                lines.append(f'😴 Dormants : {names}')
            self._set_insight_chips(lines or [t('Pas encore assez de données.')])
        if self.state.can(perms.MANAGE_CLIENT_DEBTS):
            debt_total = float(fin.get('client_debts') or 0)
            debt_count = int(fin.get('client_debts_count') or 0)
            self.card_debt.set_value(format_money(debt_total, currency))
            if debt_count <= 0:
                self.card_debt.set_hint('Aucune dette en cours — cliquer pour ouvrir')
            elif debt_count == 1:
                self.card_debt.set_hint('1 dette en cours — cliquer pour le détail')
            else:
                self.card_debt.set_hint(f'{debt_count} dettes en cours — cliquer pour le détail')
        self._stock_health.set_values(int(data['out_of_stock']), int(data['low_stock']), int(data['total_products']))
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
            days = forecast.get('days_left')
            eta = '—' if days is None else f'{days} j'
            eta_item = QTableWidgetItem(eta)
            bg, fg = _urgency_colors(days)
            eta_item.setBackground(QBrush(QColor(bg)))
            eta_item.setForeground(QBrush(QColor(fg)))
            self.alert_table.setItem(row, 0, QTableWidgetItem(product.name))
            self.alert_table.setItem(row, 1, QTableWidgetItem(format_quantity(product.quantity)))
            self.alert_table.setItem(row, 2, QTableWidgetItem(format_quantity(product.min_stock)))
            self.alert_table.setItem(row, 3, eta_item)
