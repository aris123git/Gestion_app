"""Tableau de bord Chantier Pro : l'essentiel d'un coup d'œil."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from app.i18n import t
from app.services import chantier_dashboard, chantiers_nav, permissions as perms, settings_service
from app.ui.state import AppState
from app.ui.widgets.helpers import make_card, page_title
from app.utils.helpers import format_money


def _label(html: str = "") -> QLabel:
    lab = QLabel(html)
    lab.setTextFormat(Qt.TextFormat.RichText)
    lab.setWordWrap(True)
    return lab


class ChantiersDashboardPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.can_finance = state.can(perms.VIEW_CHANTIER_FINANCE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addWidget(page_title(t("Tableau de bord")))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        self.grid = QGridLayout(body)
        self.grid.setSpacing(12)
        self.kpis = _label()
        self.watch = _label()
        self.money = _label()
        self.people = _label()
        self.grid.addWidget(make_card(self.kpis), 0, 0, 1, 2)
        self.grid.addWidget(make_card(self.watch), 1, 0)
        self.grid.addWidget(make_card(self.money), 1, 1)
        self.grid.addWidget(make_card(self.people), 2, 0, 1, 2)
        self.grid.setRowStretch(3, 1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

    @staticmethod
    def _items(rows, fmt, empty: str) -> str:
        return "<br/>".join(fmt(r) for r in rows[:6]) if rows else f"<span style='color:#64748b'>{empty}</span>"

    def refresh(self) -> None:
        cur = settings_service.get_shop_info().currency or "FCFA"
        m = lambda v: format_money(v, cur)  # noqa: E731
        d = chantier_dashboard.build()
        if self.can_finance:
            red = "#b91c1c"
            self.kpis.setText(
                f"<b>{t('Chantiers en cours')}</b> : {d.running} &nbsp;·&nbsp; <b>{t('Marchés (total)')}</b> : {m(d.contract_total)} &nbsp;·&nbsp; "
                f"<b>{t('Encaissé')}</b> : {m(d.received)} &nbsp;·&nbsp; <b>{t('Reste à encaisser')}</b> : {m(d.receivable)}<br/>"
                f"<b>{t('Dépensé')}</b> : {m(d.spent)} &nbsp;·&nbsp; <b>{t('Marge prévue')}</b> : <span style='color:{'#15803d' if d.margin >= 0 else red}'>{m(d.margin)}</span> "
                f"&nbsp;·&nbsp; <b>{t('Trésorerie')}</b> : <span style='color:{'#15803d' if d.cash >= 0 else red}'>{m(d.cash)}</span><br/>"
                f"<b>{t('Ce mois')}</b> : {t('encaissé')} {m(d.month_received)} · {t('payé')} {m(d.month_paid)}"
                + (f" &nbsp;·&nbsp; <span style='color:{red}'><b>{d.losing}</b> {t('chantier(s) en perte')}</span>" if d.losing else ""))
        else:
            self.kpis.setText(f"<b>{t('Chantiers en cours')}</b> : {d.running}")
        self.watch.setText(
            f"<b>{t('À surveiller')}</b><br/>" + self._items(d.watch, lambda r: f"<b>{r[0]}</b><br/>" + "<br/>".join("⚠ " + a for a in r[1]), t("Rien à signaler.")))
        if self.can_finance:
            parts = [f"<b>{t('Argent')}</b>"]
            parts.append(f"{t('Échéances clients (30 jours)')} :<br/>" + self._items(
                d.upcoming, lambda r: f"• {r[0]} — {r[1]} : {m(r[2])} ({r[3]:%d/%m})", t("Aucune échéance proche.")))
            parts.append(f"{t('Retenues de garantie à réclamer')} : <b>{m(d.retention_to_claim)}</b>")
            parts.append(f"{t('Dettes fournisseurs')} : <b>{m(d.supplier_debt)}</b>")
            self.money.setText("<br/>".join(parts))
        else:
            self.money.setText("")
        parts = [f"<b>{t('Équipes et partenaires')}</b>",
                 f"{t('Paie ouvriers en attente')} : <b>{m(d.payroll_due)}</b>",
                 f"{t('Sous-traitants : reste à payer')} : <b>{m(d.sub_to_pay)}</b> ({t('retenues détenues')} {m(d.sub_retention_held)})"]
        if d.sub_late:
            parts.append("<span style='color:#b91c1c'>" + t("Sous-traitants en retard") + " : " + ", ".join(f"{x[1]} ({x[0]})" for x in d.sub_late[:5]) + "</span>")
        if chantiers_nav.rentals_enabled():
            if d.rentals_overdue:
                parts.append("<span style='color:#b91c1c'>" + t("Locations en retard") + " : " + ", ".join(f"{c} ({n} j)" for c, n in d.rentals_overdue[:5]) + "</span>")
            if d.rentals_today:
                parts.append(f"{t('À rendre aujourd’hui')} : " + ", ".join(d.rentals_today[:5]))
        self.people.setText("<br/>".join(parts))
