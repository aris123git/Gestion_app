"""Page des rapports : synthèse par période et exports PDF/Excel."""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.controllers.report_controller import ReportController, period_bounds
from app.controllers.sale_controller import SaleController
from app.reports.excel_report import export_report_excel
from app.reports.pdf_report import export_report_pdf
from app.services import audit_service, permissions as perms, settings_service
from app.services.auth_service import AuthService
from app.services.cash_session_service import CashSessionService
from app.ui.dialogs.authorize_dialog import require_admin_authorization
from app.ui.dialogs.cancel_sale_dialog import CancelSaleDialog
from app.ui.state import AppState
from app.ui.widgets.helpers import (
    info,
    make_card,
    page_title,
    section_title,
    warn,
)
from app.utils.helpers import format_datetime, format_money


class ReportsPage(QWidget):
    HISTORY_LIMIT = 5000

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
        z_report = QPushButton("Z de caisse (jour)")
        z_report.clicked.connect(self._show_z_report)
        sessions_btn = QPushButton("Sessions caisse")
        sessions_btn.clicked.connect(self._show_cash_sessions)
        controls.addWidget(QLabel("Période :"))
        controls.addWidget(self.period)
        controls.addWidget(QLabel("Du"))
        controls.addWidget(self.start)
        controls.addWidget(QLabel("Au"))
        controls.addWidget(self.end)
        controls.addWidget(generate)
        controls.addWidget(z_report)
        controls.addWidget(sessions_btn)
        controls.addStretch()
        layout.addLayout(controls)
        self._period_changed(self.period.currentText())

        # Cartes de synthèse
        self.summary_grid = QGridLayout()
        self.summary_grid.setSpacing(12)
        self.lbl_revenue = self._metric("CA encaissé")
        self.lbl_debt_pay = self._metric("Règlements dettes")
        self.lbl_sales = self._metric("Nombre de ventes")
        self.lbl_profit = self._metric("Bénéfice brut")
        self.lbl_expenses = self._metric("Dépenses")
        self.lbl_net = self._metric("Bénéfice net")
        for i, widget in enumerate(
            [
                self.lbl_revenue,
                self.lbl_debt_pay,
                self.lbl_sales,
                self.lbl_profit,
                self.lbl_expenses,
                self.lbl_net,
            ]
        ):
            self.summary_grid.addWidget(widget["card"], 0, i)
        layout.addLayout(self.summary_grid)

        layout.addWidget(section_title("Top produits sur la période"))
        self.top_table = QTableWidget(0, 3)
        self.top_table.setHorizontalHeaderLabels(["Produit", "Quantité", "Total ventes"])
        self.top_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.top_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.top_table)

        # Historique détaillé des ventes (avec date et heure).
        layout.addWidget(section_title("Historique des ventes (date et heure)"))
        self.history_note = QLabel("")
        self.history_note.setStyleSheet("color: #b45309; font-size: 12px;")
        self.history_note.setWordWrap(True)
        layout.addWidget(self.history_note)
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(
            ["Ticket", "Date et heure", "Caissier", "Paiement", "Total"]
        )
        self.history_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.history_table)

        # Annulation : admin direct, gestionnaire avec autorisation admin.
        history_actions = QHBoxLayout()
        history_actions.addStretch()
        self.reprint_button = QPushButton("Réimprimer ticket")
        self.reprint_button.clicked.connect(self._reprint_selected_sale)
        history_actions.addWidget(self.reprint_button)
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
        self._apply_permissions()

    def _apply_permissions(self) -> None:
        show_profits = self.state.can(perms.VIEW_PROFITS)
        self.lbl_profit["card"].setVisible(show_profits)
        self.lbl_expenses["card"].setVisible(show_profits)
        self.lbl_net["card"].setVisible(show_profits)
        self.cancel_sale_button.setVisible(perms.can_cancel_sale(self.state.current_user))

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
        self._apply_permissions()
        start, end = self._current_range()
        self._report = ReportController.build(start, end)
        currency = settings_service.get_currency()
        self.lbl_revenue["value"].setText(
            format_money(self._report["cash_revenue"], currency)
        )
        self.lbl_debt_pay["value"].setText(
            format_money(self._report.get("debt_repayments", 0), currency)
        )
        self.lbl_sales["value"].setText(str(self._report["sales_count"]))
        if self.state.can(perms.VIEW_PROFITS):
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
        sales = SaleController.list(start=start, end=end, limit=self.HISTORY_LIMIT)
        self.history_note.setText(
            f"Historique limité aux {self.HISTORY_LIMIT} ventes les plus récentes "
            "sur la période. Réduisez la plage de dates pour afficher un sous-ensemble précis."
            if len(sales) == self.HISTORY_LIMIT
            else ""
        )
        self._sale_ids = [s.id for s in sales]
        self.history_table.setRowCount(len(sales))
        for row, sale in enumerate(sales):
            self.history_table.setItem(row, 0, QTableWidgetItem(sale.ticket_number))
            self.history_table.setItem(row, 1, QTableWidgetItem(format_datetime(sale.date)))
            self.history_table.setItem(row, 2, QTableWidgetItem(sale.cashier_name))
            self.history_table.setItem(row, 3, QTableWidgetItem(sale.payment_summary))
            total_item = QTableWidgetItem(format_money(sale.total, currency))
            if sale.status == "cancelled":
                motif = (getattr(sale, "cancel_reason", None) or "").strip()
                suffix = f" (annulée — {motif[:40]})" if motif else " (annulée)"
                total_item.setText(format_money(sale.total, currency) + suffix)
                total_item.setToolTip(motif or "Vente annulée")
            self.history_table.setItem(row, 4, total_item)

    def _format_z_report(self, report: dict) -> str:
        currency = settings_service.get_currency()
        day = report.get("day") or report["start"]
        cashier = report.get("cashier_label") or "Tous les caissiers"
        lines = [
            "Z DE CAISSE",
            f"Date : {day:%d/%m/%Y}",
            f"Périmètre : {cashier}",
            f"Généré le : {datetime.now():%d/%m/%Y %H:%M}",
            "",
            f"CA encaissé (ventes + règlements) : {format_money(report['cash_revenue'], currency)}",
            f"dont règlements dettes : {format_money(report['debt_repayments'], currency)}",
            f"Crédit client (non encaissé) : {format_money(report['credit_sales'], currency)}",
            f"Dépenses : {format_money(report['expenses'], currency)}",
            f"Règlements fournisseurs : {format_money(report['supplier_debt_payments'], currency)}",
            f"Trésorerie : {format_money(report['treasury'], currency)}",
            "",
            "Détail par mode de paiement :",
        ]
        payments = report.get("payments") or []
        if payments:
            lines.extend(
                f"- {method} : {format_money(amount, currency)}"
                for method, amount in payments
            )
        else:
            lines.append("- Aucun encaissement")
        by_cashier = report.get("by_cashier") or []
        if by_cashier:
            lines.extend(["", "Par caissier :"])
            lines.extend(
                f"- {name} : {format_money(total, currency)} ({count} ventes)"
                for name, total, count in by_cashier
            )
        return "\n".join(lines)

    def _show_z_report(self) -> None:
        qdate = self.start.date()
        day = date(qdate.year(), qdate.month(), qdate.day())
        users = AuthService.list_users()
        labels = ["Tous les caissiers"]
        ids: list = [None]
        for user in users:
            if not getattr(user, "is_active", True):
                continue
            label = user.full_name or user.username
            labels.append(f"{label} ({user.role})")
            ids.append(user.id)
        from PySide6.QtWidgets import QInputDialog

        choice, ok = QInputDialog.getItem(
            self, "Z de caisse", "Périmètre :", labels, 0, False
        )
        if not ok:
            return
        user_id = ids[labels.index(choice)]
        report = ReportController.z_report(day, user_id=user_id)
        report["cashier_label"] = choice
        content = self._format_z_report(report)

        dialog = QDialog(self)
        dialog.setWindowTitle("Z de caisse")
        dialog.setMinimumSize(520, 480)
        layout = QVBoxLayout(dialog)
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(content)
        layout.addWidget(preview)

        buttons = QHBoxLayout()
        close = QPushButton("Fermer")
        close.clicked.connect(dialog.accept)
        save = QPushButton("Enregistrer le texte")
        save.setObjectName("Primary")

        def _save() -> None:
            config.ensure_directories()
            path = (
                config.EXPORT_DIR
                / f"z_caisse_{day:%Y%m%d}_{datetime.now():%H%M%S}.txt"
            )
            path.write_text(content, encoding="utf-8")
            info(dialog, f"Z de caisse enregistré :\n{path}")

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
        lines = ["SESSIONS DE CAISSE (récentes)", ""]
        if not rows:
            lines.append("Aucune session enregistrée.")
        for sess in rows:
            user = getattr(sess, "user", None)
            name = ""
            if user is not None:
                name = getattr(user, "full_name", None) or getattr(
                    user, "username", ""
                )
            variance = float(sess.variance) if sess.variance is not None else None
            var_txt = (
                format_money(variance, currency) if variance is not None else "—"
            )
            flag = " ⚠" if variance is not None and abs(variance) >= 0.01 else ""
            lines.append(
                f"#{sess.id} {name} | ouvert {format_datetime(sess.opened_at)} | "
                f"statut={sess.status} | écart={var_txt}{flag}"
            )
            if sess.note:
                lines.append(f"    note : {sess.note}")
        dialog = QDialog(self)
        dialog.setWindowTitle("Sessions de caisse")
        dialog.setMinimumSize(640, 480)
        layout = QVBoxLayout(dialog)
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText("\n".join(lines))
        layout.addWidget(preview)
        close = QPushButton("Fermer")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def _reprint_selected_sale(self) -> None:
        """Réimprime (aperçu + impression) le ticket de la vente sélectionnée."""
        row = self.history_table.currentRow()
        if row < 0 or row >= len(self._sale_ids):
            warn(self, "Sélectionnez une vente dans l'historique.")
            return
        sale = SaleController.get(self._sale_ids[row])
        if not sale:
            warn(self, "Vente introuvable.")
            return
        from app.ui.dialogs.ticket_dialog import TicketDialog

        TicketDialog(sale, self).exec()
        audit_service.log_action(
            "Réimpression ticket",
            "Sale",
            sale.ticket_number,
            self.state.user_id,
            getattr(self.state.current_user, "username", ""),
        )

    def _cancel_selected_sale(self) -> None:
        """Annule la vente sélectionnée et remet en stock.

        Administrateur : immédiat. Gestionnaire : mot de passe admin requis.
        Motif obligatoire (≥ 10 lettres).
        """
        row = self.history_table.currentRow()
        if row < 0 or row >= len(self._sale_ids):
            warn(self, "Sélectionnez une vente dans l'historique.")
            return
        if not perms.can_cancel_sale(self.state.current_user):
            warn(self, "Vous n'avez pas l'autorisation d'annuler une vente.")
            return
        authorized_by = ""
        if perms.requires_auth_to_cancel(self.state.current_user):
            ok, authorized_by = require_admin_authorization(
                self,
                "L'annulation d'une vente nécessite l'autorisation "
                "d'un administrateur.",
            )
            if not ok:
                return
        sale_id = self._sale_ids[row]
        ticket = self.history_table.item(row, 0)
        ticket_number = ticket.text() if ticket else str(sale_id)
        dialog = CancelSaleDialog(ticket_number, parent=self)
        if not dialog.exec() or not dialog.reason:
            return
        is_admin = bool(
            self.state.current_user
            and getattr(self.state.current_user, "role", "") == perms.ROLE_ADMIN
        )
        try:
            SaleController.cancel_sale(
                sale_id,
                restock=True,
                user_id=self.state.user_id,
                username=getattr(self.state.current_user, "username", ""),
                reason=dialog.reason,
                allow_old_sales=is_admin,
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        auth_part = f" — autorisé par {authorized_by}" if authorized_by else ""
        audit_service.log_action(
            "Annulation vente",
            "Sale",
            f"{ticket_number} — motif: {dialog.reason}{auth_part}",
            self.state.user_id,
            getattr(self.state.current_user, "username", ""),
        )
        info(self, f"Vente {ticket_number} annulée et articles remis en stock.")
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

    def _export_pdf(self) -> None:
        if not self._report:
            self._generate()
        path = export_report_pdf(
            self._report,
            include_profits=self.state.can(perms.VIEW_PROFITS),
        )
        info(self, f"Rapport PDF généré :\n{path}")

    def _export_excel(self) -> None:
        if not self._report:
            self._generate()
        start, end = self._current_range()
        rows = ReportController.sales_rows(start, end)
        path = export_report_excel(
            self._report,
            rows,
            include_profits=self.state.can(perms.VIEW_PROFITS),
        )
        info(self, f"Rapport Excel généré :\n{path}")
