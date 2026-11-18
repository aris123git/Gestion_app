"""Page des rapports : cartes, courbe des ventes, modes de paiement, top produits, historique, exports."""
from __future__ import annotations
from app.i18n import t
from collections import OrderedDict
from datetime import date, datetime, timedelta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPlainTextEdit, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget
from app import config
from app.controllers.expense_controller import ExpenseController
from app.controllers.report_controller import ReportController
from app.controllers.sale_controller import SaleController
from app.reports.excel_report import export_report_excel
from app.reports.pdf_report import export_report_pdf
from app.services import audit_service, permissions as perms, settings_service
from app.services.auth_service import AuthService
from app.services.cash_session_service import CashSessionService
from app.ui.dialogs.authorize_dialog import require_admin_authorization
from app.ui.dialogs.cancel_sale_dialog import CancelSaleDialog
from app.ui.state import AppState
from app.ui.widgets.batch import enable_multi, run_batch, selected_rows
from app.ui.widgets.helpers import info, make_card, page_title, warn
from app.ui.widgets.mini_charts import LineChart, Sparkline
from app.ui.widgets.period_picker import PeriodPicker
from app.utils.helpers import format_datetime, format_money

STATUS_STYLE = {'Payée': ('#dcfce7', '#166534'), 'Crédit': ('#fef3c7', '#92400e'), 'Annulée': ('#fee2e2', '#991b1b')}


def sale_status(sale) -> str:
    if sale.status == 'cancelled':
        return 'Annulée'
    paid = sum(float(p.amount or 0) for p in (sale.payments or []))
    return 'Crédit' if float(sale.total or 0) - paid > 0.01 else 'Payée'


class ReportsPage(QWidget):
    HISTORY_LIMIT = 5000
    HEADERS = ['Ticket', 'Date et heure', 'Client', 'Caissier', 'Paiement', 'Statut', 'Total']

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._report = None
        self._sale_ids: list[int] = []
        self._all_sales: list = []
        self._shown: list = []
        self._sort = (1, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(page_title(t('Rapports')))
        top.addStretch()
        z_report = QPushButton(t('Z de caisse'))
        z_report.clicked.connect(self._show_z_report)
        sessions_btn = QPushButton(t('Sessions caisse'))
        sessions_btn.clicked.connect(self._show_cash_sessions)
        export = QPushButton(t('Exporter'))
        export.setObjectName('Primary')
        menu = QMenu(export)
        menu.addAction(t('PDF'), self._export_pdf)
        menu.addAction(t('Excel'), self._export_excel)
        export.setMenu(menu)
        for w in (z_report, sessions_btn, export):
            top.addWidget(w)
        layout.addLayout(top)
        self.picker = PeriodPicker()
        self.picker.mode.setCurrentIndex(self.picker.mode.findData('month'))
        self.picker.changed.connect(self._generate)
        prow = QHBoxLayout()
        prow.addWidget(self.picker)
        prow.addStretch(1)
        layout.addLayout(prow)
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.lbl_revenue = self._metric('CA encaissé')
        self.lbl_sales = self._metric('Nombre de ventes')
        self.lbl_profit = self._metric('Bénéfice brut')
        self.lbl_expenses = self._metric('Dépenses', bad_up=True)
        self.lbl_net = self._metric('Bénéfice net')
        for w in (self.lbl_revenue, self.lbl_sales, self.lbl_profit, self.lbl_expenses, self.lbl_net):
            cards.addWidget(w['card'], 1)
        layout.addLayout(cards)
        mid = QHBoxLayout()
        mid.setSpacing(12)
        chart_box = QWidget()
        cb = QVBoxLayout(chart_box)
        cb.setContentsMargins(0, 0, 0, 0)
        self.chart_title = QLabel()
        self.chart_title.setTextFormat(Qt.TextFormat.RichText)
        self.chart = LineChart()
        cb.addWidget(self.chart_title)
        cb.addWidget(self.chart, 1)
        mid.addWidget(make_card(chart_box), 3)
        side_box = QWidget()
        self.side = QVBoxLayout(side_box)
        self.side.setContentsMargins(0, 0, 0, 0)
        self.side.setSpacing(4)
        mid.addWidget(make_card(side_box), 2)
        layout.addLayout(mid)
        hist = QWidget()
        hl = QVBoxLayout(hist)
        hl.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel('<b>' + t('Ventes de la période') + '</b>'))
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText(t('Rechercher : client, téléphone, n° de ticket ou de facture…'))
        self.history_search.setClearButtonEnabled(True)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._load_history)
        self.history_search.textChanged.connect(lambda _t: self._search_timer.start())
        self.status_filter = QComboBox()
        for label in ('Toutes', 'Payée', 'Crédit', 'Annulée'):
            self.status_filter.addItem(t(label), label)
        self.status_filter.currentIndexChanged.connect(lambda _i: self._load_history())
        bar.addWidget(self.history_search, 1)
        bar.addWidget(self.status_filter)
        hl.addLayout(bar)
        self.history_note = QLabel('')
        self.history_note.setStyleSheet('color: #b45309; font-size: 12px;')
        self.history_note.setWordWrap(True)
        hl.addWidget(self.history_note)
        self.history_table = QTableWidget(0, len(self.HEADERS))
        self.history_table.setHorizontalHeaderLabels([t(h) for h in self.HEADERS])
        hh = self.history_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionsClickable(True)
        hh.sectionClicked.connect(self._sort_by)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.verticalHeader().setDefaultSectionSize(36)
        self.history_table.setShowGrid(False)
        self.history_table.setMinimumHeight(220)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        enable_multi(self.history_table)
        hl.addWidget(self.history_table, 1)
        foot = QHBoxLayout()
        self.history_count = QLabel('')
        self.history_count.setStyleSheet('color: #64748b;')
        foot.addWidget(self.history_count)
        foot.addStretch()
        self.reprint_button = QPushButton(t('Réimprimer ticket'))
        self.reprint_button.clicked.connect(self._reprint_selected_sale)
        self.cancel_sale_button = QPushButton(t('Annuler la vente sélectionnée'))
        self.cancel_sale_button.setObjectName('DangerOutline')
        self.cancel_sale_button.clicked.connect(self._cancel_selected_sale)
        foot.addWidget(self.reprint_button)
        foot.addWidget(self.cancel_sale_button)
        hl.addLayout(foot)
        layout.addWidget(make_card(hist), 1)
        self._apply_permissions()

    def _apply_permissions(self) -> None:
        show_profits = self.state.can(perms.VIEW_PROFITS)
        for w in (self.lbl_profit, self.lbl_expenses, self.lbl_net):
            w['card'].setVisible(show_profits)
        self.cancel_sale_button.setVisible(perms.can_cancel_sale(self.state.current_user))

    def _metric(self, title: str, bad_up: bool = False) -> dict:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(4, 4, 4, 4)
        text = QLabel()
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setMinimumHeight(58)
        spark = Sparkline('#b91c1c' if bad_up else '#2563eb')
        row.addWidget(text, 1)
        row.addWidget(spark, 0, Qt.AlignmentFlag.AlignTop)
        return {'card': make_card(wrap), 'text': text, 'spark': spark, 'title': title, 'bad_up': bad_up}

    def _set_metric(self, m: dict, value: str, now: float, before: float, series: list[float], extra: str = '') -> None:
        if before:
            pct = (now - before) / abs(before) * 100
            good = (pct >= 0) != m['bad_up']
            color = '#15803d' if good else '#b91c1c'
            delta = f"<span style='color:{color};font-size:11px'>{'▲' if pct >= 0 else '▼'} {abs(pct):.1f} % {t('vs période précédente')}</span>"
        else:
            delta = f"<span style='color:#94a3b8;font-size:11px'>{t('Pas de comparaison')}</span>"
        sub = f"<br><span style='color:#64748b;font-size:11px'>{extra}</span>" if extra else ''
        m['text'].setText(f"<span style='color:#64748b;font-size:12px'>{t(m['title'])}</span><br><b style='font-size:19px'>{value}</b><br>{delta}{sub}")
        m['spark'].set_values(series)

    @staticmethod
    def _buckets(start: date, end: date):
        """Jours (ou mois si la période dépasse ~2 mois) de la période : liste de (clé, étiquette)."""
        out = []
        if (end - start).days > 62:
            cur = start.replace(day=1)
            while cur <= end:
                out.append(((cur.year, cur.month), f'{cur:%m/%y}'))
                cur = (cur + timedelta(days=32)).replace(day=1)
        else:
            cur = start
            while cur <= end:
                out.append((cur, f'{cur:%d/%m}'))
                cur += timedelta(days=1)
        return out, (end - start).days > 62

    def _generate(self) -> None:
        self._apply_permissions()
        start, end = self.picker.period()
        days = (end - start).days + 1
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=days - 1)
        self._report = ReportController.build(start, end)
        prev = ReportController.build(prev_start, prev_end)
        currency = settings_service.get_currency()
        rep = self._report
        buckets, monthly = self._buckets(start, end)
        keyf = (lambda d: (d.year, d.month)) if monthly else (lambda d: d)
        rev = OrderedDict((k, 0.0) for k, _l in buckets)
        cnt = OrderedDict((k, 0.0) for k, _l in buckets)
        prof = OrderedDict((k, 0.0) for k, _l in buckets)
        exp = OrderedDict((k, 0.0) for k, _l in buckets)
        self._all_sales = SaleController.list(start=start, end=end, limit=self.HISTORY_LIMIT)
        for s in self._all_sales:
            k = keyf(s.date.date())
            if s.status == 'cancelled' or k not in rev:
                continue
            rev[k] += float(s.total or 0)
            cnt[k] += 1
            prof[k] += float(s.profit or 0)
        show_profits = self.state.can(perms.VIEW_PROFITS)
        if show_profits:
            for e in ExpenseController.list(start=start, end=end, limit=20000):
                k = keyf(e.date.date())
                if k in exp:
                    exp[k] += float(e.amount or 0)
        net = [prof[k] - exp[k] for k in prof]
        debt = rep.get('debt_repayments', 0)
        extra = f"{t('dont règlements dettes')} : {format_money(debt, currency)}" if debt else ''
        self._set_metric(self.lbl_revenue, format_money(rep['cash_revenue'], currency), rep['cash_revenue'], prev['cash_revenue'], list(rev.values()), extra)
        self._set_metric(self.lbl_sales, str(rep['sales_count']), rep['sales_count'], prev['sales_count'], list(cnt.values()))
        if show_profits:
            self._set_metric(self.lbl_profit, format_money(rep['profit'], currency), rep['profit'], prev['profit'], list(prof.values()))
            self._set_metric(self.lbl_expenses, format_money(rep['expenses'], currency), rep['expenses'], prev['expenses'], list(exp.values()))
            self._set_metric(self.lbl_net, format_money(rep['net_profit'], currency), rep['net_profit'], prev['net_profit'], net)
        self.chart_title.setText(f"<b>{t('Ventes dans le temps')}</b> <span style='color:#64748b'>· {t('par mois') if monthly else t('par jour')}</span>")
        self.chart.set_data([l for _k, l in buckets], list(rev.values()))
        self._fill_side(rep, currency)
        self._load_history(use_cache=True)

    @staticmethod
    def _pair(left: str, right: str) -> QWidget:
        w = QWidget()
        w.setStyleSheet('background: transparent;')
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 6, 0, 0)
        a, b = QLabel(left), QLabel(right)
        for x in (a, b):
            x.setTextFormat(Qt.TextFormat.RichText)
        h.addWidget(a, 1)
        h.addWidget(b)
        return w

    def _fill_side(self, rep: dict, currency: str) -> None:
        while self.side.count():
            it = self.side.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.side.addWidget(QLabel('<b>' + t('Modes de paiement') + '</b>'))
        payments = [(m, v) for m, v in rep.get('payments') or [] if v]
        total = sum(v for _m, v in payments)
        if not payments:
            self.side.addWidget(QLabel(t('Aucun encaissement.')))
        for method, value in sorted(payments, key=lambda mv: -mv[1]):
            pct = value / total * 100 if total else 0
            line = self._pair(method, f"<b>{format_money(value, currency)} · {pct:.0f} %</b>")
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(round(pct)))
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            bar.setStyleSheet('QProgressBar {background: #e2e8f0; border: none; border-radius: 5px;} QProgressBar::chunk {background: #2563eb; border-radius: 5px;}')
            self.side.addWidget(line)
            self.side.addWidget(bar)
        self.side.addSpacing(10)
        self.side.addWidget(QLabel('<b>' + t('Top produits') + '</b>'))
        top = rep['top_products'][:5]
        if not top:
            self.side.addWidget(QLabel(t('Aucune vente.')))
        for name, qty, amount in top:
            self.side.addWidget(self._pair(f"{name} <span style='color:#64748b'>× {qty:g}</span>", f"<b>{format_money(amount, currency)}</b>"))
        self.side.addStretch(1)

    def _sort_by(self, col: int) -> None:
        self._sort = (col, not self._sort[1]) if self._sort[0] == col else (col, False)
        self._render_history()

    def _load_history(self, use_cache: bool = False) -> None:
        """Ventes de la période, filtrées par la recherche (client, téléphone, n° ticket/facture) et le statut."""
        text = self.history_search.text().strip()
        if text:
            start, end = self.picker.period()
            sales = SaleController.list(search=text, start=start, end=end, limit=self.HISTORY_LIMIT)
        else:
            sales = self._all_sales
        want = self.status_filter.currentData()
        self._shown = [s for s in sales if want in (None, 'Toutes') or sale_status(s) == want]
        self.history_note.setText(f'Historique limité aux {self.HISTORY_LIMIT} ventes les plus récentes sur la période. Réduisez la plage de dates pour afficher un sous-ensemble précis.' if len(sales) >= self.HISTORY_LIMIT else '')
        self._render_history()

    def _render_history(self) -> None:
        currency = settings_service.get_currency()
        keys = {0: lambda s: s.ticket_number, 1: lambda s: s.date, 2: lambda s: (s.client.name if s.client else '').lower(), 3: lambda s: (s.cashier_name or '').lower(), 4: lambda s: s.payment_summary, 5: sale_status, 6: lambda s: float(s.total or 0)}
        col, desc = self._sort
        sales = sorted(self._shown, key=keys.get(col, keys[1]), reverse=desc)
        self._sale_ids = [s.id for s in sales]
        self.history_count.setText(f'{len(sales)} {t("vente(s)")}')
        self.history_table.setRowCount(len(sales))
        for row, sale in enumerate(sales):
            status = sale_status(sale)
            total_text = format_money(sale.total, currency)
            total = QTableWidgetItem(total_text)
            total.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            st = QTableWidgetItem(status)
            bg, fg = STATUS_STYLE[status]
            st.setBackground(QBrush(QColor(bg)))
            st.setForeground(QBrush(QColor(fg)))
            st.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if status == 'Annulée':
                motif = (getattr(sale, 'cancel_reason', None) or '').strip()
                st.setToolTip(motif or 'Vente annulée')
                total.setToolTip(motif or 'Vente annulée')
            for c, item in enumerate([QTableWidgetItem(sale.ticket_number), QTableWidgetItem(format_datetime(sale.date)), QTableWidgetItem(sale.client.name if sale.client else ''), QTableWidgetItem(sale.cashier_name), QTableWidgetItem(sale.payment_summary), st, total]):
                self.history_table.setItem(row, c, item)

    def _format_z_report(self, report: dict) -> str:
        currency = settings_service.get_currency()
        day = report.get('day') or report['start']
        cashier = report.get('cashier_label') or 'Tous les caissiers'
        lines = ['Z DE CAISSE', f'Date : {day:%d/%m/%Y}', f'Périmètre : {cashier}', f'Généré le : {datetime.now():%d/%m/%Y %H:%M}', '', f'CA encaissé (ventes + règlements) : {format_money(report['cash_revenue'], currency)}', f'dont règlements dettes : {format_money(report['debt_repayments'], currency)}', f'Crédit client (non encaissé) : {format_money(report['credit_sales'], currency)}', f'Dépenses : {format_money(report['expenses'], currency)}', f'Règlements fournisseurs : {format_money(report['supplier_debt_payments'], currency)}', f'Trésorerie : {format_money(report['treasury'], currency)}', '', 'Détail par mode de paiement :']
        payments = report.get('payments') or []
        if payments:
            lines.extend((f'- {method} : {format_money(amount, currency)}' for method, amount in payments))
        else:
            lines.append('- Aucun encaissement')
        by_cashier = report.get('by_cashier') or []
        if by_cashier:
            lines.extend(['', 'Par caissier :'])
            lines.extend((f'- {name} : {format_money(total, currency)} ({count} ventes)' for name, total, count in by_cashier))
        return '\n'.join(lines)

    def _show_z_report(self) -> None:
        day = min(self.picker.period()[1], date.today())
        users = AuthService.list_users()
        labels = ['Tous les caissiers']
        ids: list = [None]
        for user in users:
            if not getattr(user, 'is_active', True):
                continue
            label = user.full_name or user.username
            labels.append(f'{label} ({user.role})')
            ids.append(user.id)
        from PySide6.QtWidgets import QInputDialog
        choice, ok = QInputDialog.getItem(self, 'Z de caisse', 'Périmètre :', labels, 0, False)
        if not ok:
            return
        user_id = ids[labels.index(choice)]
        report = ReportController.z_report(day, user_id=user_id)
        report['cashier_label'] = choice
        content = self._format_z_report(report)
        dialog = QDialog(self)
        dialog.setWindowTitle(t('Z de caisse'))
        dialog.setMinimumSize(520, 480)
        layout = QVBoxLayout(dialog)
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(content)
        layout.addWidget(preview)
        buttons = QHBoxLayout()
        close = QPushButton(t('Fermer'))
        close.clicked.connect(dialog.accept)
        save = QPushButton(t('Enregistrer le texte'))
        save.setObjectName('Primary')

        def _save() -> None:
            config.ensure_directories()
            path = config.EXPORT_DIR / f'z_caisse_{day:%Y%m%d}_{datetime.now():%H%M%S}.txt'
            path.write_text(content, encoding='utf-8')
            info(dialog, f'Z de caisse enregistré :\n{path}')
        save.clicked.connect(_save)
        buttons.addWidget(close)
        buttons.addStretch()
        buttons.addWidget(save)
        layout.addLayout(buttons)
        dialog.exec()

    def _show_cash_sessions(self) -> None:
        """Liste des dernières sessions (écarts visibles pour le patron)."""
        currency = settings_service.get_currency()
        rows = CashSessionService.recent(limit=40)
        lines = ['SESSIONS DE CAISSE (récentes)', '']
        if not rows:
            lines.append('Aucune session enregistrée.')
        for sess in rows:
            user = getattr(sess, 'user', None)
            name = ''
            if user is not None:
                name = getattr(user, 'full_name', None) or getattr(user, 'username', '')
            variance = float(sess.variance) if sess.variance is not None else None
            var_txt = format_money(variance, currency) if variance is not None else '—'
            flag = ' ⚠' if variance is not None and abs(variance) >= 0.01 else ''
            lines.append(f'#{sess.id} {name} | ouvert {format_datetime(sess.opened_at)} | statut={sess.status} | écart={var_txt}{flag}')
            if sess.note:
                lines.append(f'    note : {sess.note}')
        dialog = QDialog(self)
        dialog.setWindowTitle(t('Sessions de caisse'))
        dialog.setMinimumSize(640, 480)
        layout = QVBoxLayout(dialog)
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText('\n'.join(lines))
        layout.addWidget(preview)
        close = QPushButton(t('Fermer'))
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def _reprint_selected_sale(self) -> None:
        """Réimprime (aperçu + impression) le ticket de la vente sélectionnée."""
        row = self.history_table.currentRow()
        if row < 0 or row >= len(self._sale_ids):
            warn(self, t("Sélectionnez une vente dans l'historique."))
            return
        sale = SaleController.get(self._sale_ids[row])
        if not sale:
            warn(self, t('Vente introuvable.'))
            return
        from app.ui.dialogs.ticket_dialog import TicketDialog
        TicketDialog(sale, self, auto_print=False).exec()
        audit_service.log_action('Réimpression ticket', 'Sale', sale.ticket_number, self.state.user_id, getattr(self.state.current_user, 'username', ''))

    def _cancel_many(self, rows: list[int]) -> None:
        """Annule plusieurs ventes avec un seul motif (l'autorisation admin a déjà été demandée une fois)."""
        dialog = CancelSaleDialog('', parent=self, many=len(rows))
        if not dialog.exec() or not dialog.reason:
            return
        user = getattr(self.state.current_user, 'username', '')
        is_admin = bool(self.state.current_user and getattr(self.state.current_user, 'role', '') == perms.ROLE_ADMIN)

        def one(sale_id: int) -> None:
            SaleController.cancel_sale(sale_id, restock=True, user_id=self.state.user_id, username=user, reason=dialog.reason, allow_old_sales=is_admin)
            audit_service.log_action('Annulation vente', 'Sale', f'#{sale_id} — motif: {dialog.reason}', self.state.user_id, user)

        items = [(self._sale_ids[r], self.history_table.item(r, 0).text()) for r in rows]
        run_batch(self, None, items, one, t("vente(s) annulée(s)"))
        self.state.notify_data_changed()

    def _cancel_selected_sale(self) -> None:
        """Annule la vente sélectionnée et remet en stock.

        Administrateur : immédiat. Gestionnaire : mot de passe admin requis.
        Motif obligatoire (≥ 10 lettres).
        """
        rows = selected_rows(self.history_table)
        row = self.history_table.currentRow()
        if row < 0 or row >= len(self._sale_ids):
            warn(self, t("Sélectionnez une vente dans l'historique."))
            return
        if not perms.can_cancel_sale(self.state.current_user):
            warn(self, t("Vous n'avez pas l'autorisation d'annuler une vente."))
            return
        authorized_by = ''
        if perms.requires_auth_to_cancel(self.state.current_user):
            ok, authorized_by = require_admin_authorization(self, "L'annulation d'une vente nécessite l'autorisation d'un administrateur.")
            if not ok:
                return
        if len(rows) > 1:
            return self._cancel_many(rows)
        sale_id = self._sale_ids[row]
        ticket = self.history_table.item(row, 0)
        ticket_number = ticket.text() if ticket else str(sale_id)
        dialog = CancelSaleDialog(ticket_number, parent=self)
        if not dialog.exec() or not dialog.reason:
            return
        is_admin = bool(self.state.current_user and getattr(self.state.current_user, 'role', '') == perms.ROLE_ADMIN)
        try:
            SaleController.cancel_sale(sale_id, restock=True, user_id=self.state.user_id, username=getattr(self.state.current_user, 'username', ''), reason=dialog.reason, allow_old_sales=is_admin)
        except ValueError as exc:
            warn(self, str(exc))
            return
        auth_part = f' — autorisé par {authorized_by}' if authorized_by else ''
        audit_service.log_action('Annulation vente', 'Sale', f'{ticket_number} — motif: {dialog.reason}{auth_part}', self.state.user_id, getattr(self.state.current_user, 'username', ''))
        info(self, f'Vente {ticket_number} annulée et articles remis en stock.')
        self._generate()
        self.state.notify_data_changed()

    def refresh(self) -> None:
        self._generate()

    def select_sale(self, sale_id: int) -> None:
        if sale_id not in self._sale_ids:
            self._generate()
        if sale_id in self._sale_ids:
            row = self._sale_ids.index(sale_id)
            self.history_table.selectRow(row)
            item = self.history_table.item(row, 0)
            if item:
                self.history_table.scrollToItem(item)

    def _choose_sections(self, pdf: bool):
        """Fenêtre de choix des sections à exporter (mémorisée). None = annulé."""
        from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox
        from app.reports.excel_report import PROFIT_SECTIONS, SECTIONS
        from app.services import settings_service

        key = 'report_export_sections'
        saved = settings_service.get_setting(key, '')
        chosen = set(saved.split(',')) if saved else {k for k, _ in SECTIONS}
        can_profit = self.state.can(perms.VIEW_PROFITS)
        dialog = QDialog(self)
        dialog.setWindowTitle(t('Contenu de l\'export'))
        box = QVBoxLayout(dialog)
        box.addWidget(QLabel(t('Cochez les sections à inclure :')))
        checks = {}
        for sec, label in SECTIONS:
            if sec in PROFIT_SECTIONS and not can_profit:
                continue
            if pdf and sec == 'lines':
                continue
            cb = QCheckBox(t(label))
            cb.setChecked(sec in chosen)
            box.addWidget(cb)
            checks[sec] = cb
        if pdf:
            box.addWidget(QLabel(t('Le détail des lignes vendues est disponible dans l\'export Excel.')))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        if not dialog.exec():
            return None
        picked = {k for k, cb in checks.items() if cb.isChecked()}
        # Conserve aussi les choix des sections masquées (droits / PDF).
        settings_service.set_setting(key, ','.join(sorted(picked | (chosen - set(checks)))))
        return picked

    def _export_pdf(self) -> None:
        if not self._report:
            self._generate()
        sections = self._choose_sections(pdf=True)
        if sections is None:
            return
        path = export_report_pdf(self._report, include_profits=self.state.can(perms.VIEW_PROFITS), sections=sections)
        info(self, f'Rapport PDF généré :\n{path}')

    def _export_excel(self) -> None:
        if not self._report:
            self._generate()
        sections = self._choose_sections(pdf=False)
        if sections is None:
            return
        start, end = self.picker.period()
        rows = ReportController.sales_rows(start, end)
        path = export_report_excel(self._report, rows, include_profits=self.state.can(perms.VIEW_PROFITS), sections=sections)
        info(self, f'Rapport Excel généré :\n{path}')
