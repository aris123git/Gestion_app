"""Tables de salle — Maquis Caisse PC."""
from __future__ import annotations
from app.i18n import t
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget
from app.models.dining_table import STATUS_FREE, STATUS_OCCUPIED
from app.services import order_service, table_service
from app.ui.widgets.helpers import confirm, info, warn

class TablesPage(QWidget):

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        title = QLabel(t('Tables'))
        title.setObjectName('PageTitle')
        layout.addWidget(title)
        layout.addWidget(QLabel(t('Plan de salle Maquis Caisse. Ouvrez une commande depuis une table libre.')))
        add_row = QHBoxLayout()
        self.number = QLineEdit()
        self.number.setPlaceholderText(t('N°'))
        self.number.setFixedWidth(80)
        self.name = QLineEdit()
        self.name.setPlaceholderText(t('Nom (ex. Terrasse)'))
        self.capacity = QSpinBox()
        self.capacity.setRange(1, 40)
        self.capacity.setValue(4)
        add_btn = QPushButton(t('Ajouter une table'))
        add_btn.clicked.connect(self._add)
        add_row.addWidget(self.number)
        add_row.addWidget(self.name, 1)
        add_row.addWidget(QLabel(t('Couverts')))
        add_row.addWidget(self.capacity)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(10)
        layout.addWidget(self.grid_host, 1)
        refresh = QPushButton(t('Actualiser'))
        refresh.clicked.connect(self.refresh)
        layout.addWidget(refresh)
        table_service.TableService.ensure_defaults()
        self.refresh()

    def refresh(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        tables = table_service.TableService.list()
        for i, table in enumerate(tables):
            card = QPushButton(f'{table.display_name}\n{table.status} · {table.capacity} cov.')
            card.setMinimumHeight(90)
            if table.status == STATUS_OCCUPIED:
                card.setStyleSheet('QPushButton { background:#fee2e2; border:1px solid #f87171; border-radius:10px; font-weight:600; }')
            else:
                card.setStyleSheet('QPushButton { background:#ecfdf5; border:1px solid #34d399; border-radius:10px; font-weight:600; }')
            tid = table.id
            card.clicked.connect(lambda _=False, t=tid, s=table.status: self._on_table(t, s))
            self.grid.addWidget(card, i // 4, i % 4)

    def _add(self) -> None:
        try:
            table_service.TableService.create(number=self.number.text().strip() or str(len(table_service.TableService.list()) + 1), name=self.name.text().strip(), capacity=int(self.capacity.value()))
            self.number.clear()
            self.name.clear()
            self.refresh()
        except Exception as exc:
            warn(self, str(exc))

    def _on_table(self, table_id: int, status: str) -> None:
        if status == STATUS_FREE:
            if not confirm(self, t('Ouvrir une commande sur cette table ?'), t('Table')):
                return
            try:
                user = getattr(self.state, 'current_user', None)
                order = order_service.OrderService.open_on_table(table_id, opened_by=getattr(user, 'id', None))
                info(self, f'Commande {order.public_id} ouverte.')
                self.refresh()
            except Exception as exc:
                warn(self, str(exc))
        else:
            info(self, t("Table occupée. Gérez la commande dans l'écran Commandes."))
