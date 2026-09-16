"""Plan de salle tactile — Maquis Caisse PC.

Chaque table affiche son état, son ardoise en cours (total, articles, durée) et
ouvre directement l'écran de saisie tactile des produits.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t
from app.models.dining_table import (
    STATUS_CLEANING,
    STATUS_FREE,
    STATUS_OCCUPIED,
    STATUS_RESERVED,
)
from app.services import settings_service
from app.services.order_service import OrderService
from app.services.table_service import TableService
from app.ui.pages.order_entry import OrderEntryDialog
from app.ui.widgets.helpers import confirm, info, page_title, warn
from app.utils.helpers import format_money, format_quantity

STATUS_CHOICES = (STATUS_FREE, STATUS_OCCUPIED, STATUS_RESERVED, STATUS_CLEANING)

CARD_STYLES = {
    STATUS_FREE: ('#ecfdf5', '#34d399'),
    STATUS_OCCUPIED: ('#fef2f2', '#f87171'),
    STATUS_RESERVED: ('#eff6ff', '#60a5fa'),
    STATUS_CLEANING: ('#fefce8', '#facc15'),
}


def _elapsed_label(since: Optional[datetime]) -> str:
    if since is None:
        return ''
    minutes = max(0, int((datetime.now() - since).total_seconds() // 60))
    if minutes < 60:
        return t('{minutes} min').format(minutes=minutes)
    return t('{hours} h {minutes:02d}').format(hours=minutes // 60, minutes=minutes % 60)


class TableDialog(QDialog):
    """Création / modification d'une table de salle."""

    def __init__(self, table=None, parent=None):
        super().__init__(parent)
        self.table = table
        self.data: Optional[dict] = None
        self.setWindowTitle(t('Table'))
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        form = QFormLayout()
        self.number = QLineEdit(getattr(table, 'number', '') or '')
        self.number.setPlaceholderText(t('N°'))
        self.name = QLineEdit(getattr(table, 'name', '') or '')
        self.name.setPlaceholderText(t('Nom (ex. Terrasse)'))
        self.capacity = QSpinBox()
        self.capacity.setRange(1, 40)
        self.capacity.setValue(int(getattr(table, 'capacity', 4) or 4))
        form.addRow(t('N°'), self.number)
        form.addRow(t('Nom'), self.name)
        form.addRow(t('Couverts'), self.capacity)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        cancel = QPushButton(t('common.cancel'))
        cancel.clicked.connect(self.reject)
        save = QPushButton(t('common.save'))
        save.setObjectName('Primary')
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _save(self) -> None:
        self.data = {
            'number': self.number.text().strip(),
            'name': self.name.text().strip(),
            'capacity': int(self.capacity.value()),
        }
        self.accept()


class TablesPage(QWidget):
    """Plan de salle : une tuile par table, ouverture directe de l'ardoise."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.addWidget(page_title(t('Tables')))
        header.addStretch(1)
        add_btn = QPushButton(t('+ Table'))
        add_btn.setObjectName('Primary')
        add_btn.setMinimumHeight(44)
        add_btn.clicked.connect(self._add)
        refresh_btn = QPushButton(t('Actualiser'))
        refresh_btn.setMinimumHeight(44)
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(add_btn)
        header.addWidget(refresh_btn)
        layout.addLayout(header)
        hint = QLabel(
            t(
                'Touchez une table pour saisir les produits. Table verte = libre, '
                'rouge = ardoise en cours.'
            )
        )
        hint.setWordWrap(True)
        hint.setStyleSheet('color: #64748b;')
        layout.addWidget(hint)
        self.summary = QLabel('')
        self.summary.setStyleSheet('font-size: 15px; font-weight: 600;')
        layout.addWidget(self.summary)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(self.grid_host)
        layout.addWidget(scroll, 1)
        TableService.ensure_defaults()
        self._timer = QTimer(self)
        self._timer.setInterval(60000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    # --- Rendu -------------------------------------------------------------
    def refresh(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        currency = settings_service.get_currency()
        tables = TableService.list()
        summary = OrderService.open_summary_by_table()
        columns = 4
        for index, table in enumerate(tables):
            card = self._build_card(table, summary.get(int(table.id)), currency)
            self.grid.addWidget(card, index // columns, index % columns)
        open_total = sum(entry['total'] for entry in summary.values())
        self.summary.setText(
            t('{occupied} table(s) occupée(s) sur {total} — en cours : {amount}').format(
                occupied=len(summary),
                total=len(tables),
                amount=format_money(open_total, currency),
            )
        )

    def _build_card(self, table, entry, currency: str) -> QWidget:
        status = table.status if not entry else STATUS_OCCUPIED
        background, border = CARD_STYLES.get(status, CARD_STYLES[STATUS_FREE])
        card = QWidget()
        card.setFixedSize(230, 168)
        card.setStyleSheet(
            f'background: {background}; border: 2px solid {border}; border-radius: 14px;'
        )
        box = QVBoxLayout(card)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(4)
        title = QLabel(table.display_name)
        title.setStyleSheet('font-size: 18px; font-weight: 800; border: none;')
        box.addWidget(title)
        meta = QLabel(
            t('{status} · {capacity} couverts').format(
                status=status, capacity=table.capacity
            )
        )
        meta.setStyleSheet('font-size: 12px; color: #475569; border: none;')
        box.addWidget(meta)
        if entry:
            total = QLabel(format_money(entry['total'], currency))
            total.setStyleSheet(
                'font-size: 20px; font-weight: 800; color: #b91c1c; border: none;'
            )
            box.addWidget(total)
            detail = t('{items} article(s)').format(
                items=format_quantity(entry['items'])
            )
            elapsed = _elapsed_label(entry.get('since'))
            if elapsed:
                detail = f"{detail} · {elapsed}"
            if entry['orders'] > 1:
                detail = f"{detail} · {entry['orders']} " + t('commandes')
            info_label = QLabel(detail)
            info_label.setStyleSheet('font-size: 12px; color: #475569; border: none;')
            box.addWidget(info_label)
        else:
            free_label = QLabel(t('Libre — touchez pour ouvrir'))
            free_label.setWordWrap(True)
            free_label.setStyleSheet('font-size: 12px; color: #047857; border: none;')
            box.addWidget(free_label)
        box.addStretch(1)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        open_btn = QPushButton(t('Ouvrir') if not entry else t('Ardoise'))
        open_btn.setMinimumHeight(40)
        open_btn.setStyleSheet(
            'QPushButton { border: none; border-radius: 8px; background: #2563eb;'
            ' color: white; font-weight: 700; }'
        )
        open_btn.clicked.connect(lambda _=False, tid=int(table.id): self._open_table(tid))
        actions.addWidget(open_btn, 2)
        menu_btn = QPushButton('⋯')
        menu_btn.setMinimumHeight(40)
        menu_btn.setFixedWidth(46)
        menu_btn.setToolTip(t('Modifier, état, suppression'))
        menu_btn.setStyleSheet(
            'QPushButton { border: none; border-radius: 8px; background: #ffffff;'
            ' font-size: 18px; font-weight: 800; }'
        )
        menu_btn.clicked.connect(lambda _=False, tid=int(table.id): self._manage(tid))
        actions.addWidget(menu_btn)
        box.addLayout(actions)
        return card

    # --- Actions -----------------------------------------------------------
    def _open_table(self, table_id: int) -> None:
        orders = OrderService.open_for_table(table_id)
        if not orders:
            user = getattr(self.state, 'current_user', None)
            try:
                order = OrderService.open_on_table(
                    table_id, opened_by=getattr(user, 'id', None)
                )
            except ValueError as exc:
                warn(self, str(exc))
                return
            order_id = order.id
        elif len(orders) == 1:
            order_id = orders[0].id
        else:
            labels = [
                f"{o.public_id} · {format_money(float(o.total or 0), settings_service.get_currency())}"
                for o in orders
            ]
            choice, ok = QInputDialog.getItem(
                self, t('Commandes'), t('Commande à ouvrir :'), labels, 0, False
            )
            if not ok:
                return
            order_id = orders[labels.index(choice)].id
        self._open_order(order_id)

    def _open_order(self, order_id: int) -> None:
        try:
            dialog = OrderEntryDialog(self.state, order_id, self)
        except ValueError as exc:
            warn(self, str(exc))
            return
        dialog.exec()
        self.refresh()
        self.state.notify_data_changed()

    def _add(self) -> None:
        dialog = TableDialog(parent=self)
        if not dialog.exec() or not dialog.data:
            return
        data = dialog.data
        number = data['number'] or str(len(TableService.list()) + 1)
        try:
            TableService.create(
                number=number, name=data['name'], capacity=data['capacity']
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()

    def _manage(self, table_id: int) -> None:
        table = next((tb for tb in TableService.list() if tb.id == table_id), None)
        if table is None:
            return
        options = [t('Modifier la table'), t("Changer l'état"), t('Supprimer la table')]
        choice, ok = QInputDialog.getItem(
            self, table.display_name, t('Action :'), options, 0, False
        )
        if not ok:
            return
        if choice == options[0]:
            self._edit(table)
        elif choice == options[1]:
            self._change_status(table)
        else:
            self._delete(table)

    def _edit(self, table) -> None:
        dialog = TableDialog(table, parent=self)
        if not dialog.exec() or not dialog.data:
            return
        try:
            TableService.update(
                table.id,
                number=dialog.data['number'],
                name=dialog.data['name'],
                capacity=dialog.data['capacity'],
            )
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()

    def _change_status(self, table) -> None:
        choice, ok = QInputDialog.getItem(
            self,
            table.display_name,
            t('Nouvel état :'),
            list(STATUS_CHOICES),
            max(0, list(STATUS_CHOICES).index(table.status) if table.status in STATUS_CHOICES else 0),
            False,
        )
        if not ok:
            return
        if choice != STATUS_OCCUPIED and OrderService.open_for_table(table.id):
            warn(
                self,
                t('Cette table a une ardoise en cours : encaissez ou annulez la commande.'),
            )
            return
        try:
            TableService.set_status(table.id, choice)
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()

    def _delete(self, table) -> None:
        if OrderService.open_for_table(table.id):
            warn(self, t('Impossible : une ardoise est en cours sur cette table.'))
            return
        if not confirm(
            self,
            t('Supprimer « {name} » ?').format(name=table.display_name),
            t('Table'),
        ):
            return
        TableService.delete(table.id)
        info(self, t('Table supprimée.'))
        self.refresh()
