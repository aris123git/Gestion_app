"""Page de gestion des utilisateurs (administrateur uniquement)."""
from __future__ import annotations
from app.i18n import t
from datetime import date
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from app import config
from app.services import permissions as perms, product_profile
from app.services.auth_service import AuthService
from app.ui.state import AppState
from sqlalchemy import func, select
from app.database.connection import session_scope
from app.models.sale import Sale
from app.ui.widgets.batch import enable_multi, run_batch, selected_rows
from app.ui.widgets.helpers import confirm, make_card, page_title, warn
from app.utils.helpers import format_money
from app.services import settings_service
from app.utils.security import validate_password

class UserDialog(QDialog):
    """Formulaire de création / modification d'un utilisateur."""

    def __init__(self, user=None, parent=None):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle(t('Utilisateur'))
        self.setModal(True)
        self.setMinimumWidth(400)
        self.data = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        form = QFormLayout()
        form.setSpacing(10)
        self.username = QLineEdit()
        self.full_name = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText(t('Minimum 6 caractères'))
        self.role = QComboBox()
        self.role.addItems(config.ROLES)
        self.active = QCheckBox('Compte actif')
        self.active.setChecked(True)
        self.waitress = QCheckBox(t('Serveuse (caisse Maquis)'))
        self.waitress.setVisible(product_profile.is_maquis())
        self.commission_rate = QDoubleSpinBox()
        self.commission_rate.setRange(0, 100)
        self.commission_rate.setDecimals(1)
        self.commission_rate.setSuffix(' %')
        self.commission_row_label = QLabel(t('Commission / pourboire'))
        form.addRow(t("Nom d'utilisateur *"), self.username)
        form.addRow(t('Nom complet'), self.full_name)
        password_label = 'Mot de passe *' if not user else 'Nouveau mot de passe'
        form.addRow(password_label, self.password)
        form.addRow(t('Rôle'), self.role)
        form.addRow('', self.active)
        if product_profile.is_maquis():
            form.addRow('', self.waitress)
            form.addRow(self.commission_row_label, self.commission_rate)
            self.waitress.toggled.connect(self._sync_commission_visibility)
            self._sync_commission_visibility(self.waitress.isChecked())
        layout.addLayout(form)
        buttons = QHBoxLayout()
        cancel = QPushButton(t('Annuler'))
        cancel.clicked.connect(self.reject)
        save = QPushButton(t('Enregistrer'))
        save.setObjectName('Primary')
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(save)
        layout.addLayout(buttons)
        if user:
            self.username.setText(user.username)
            self.username.setEnabled(False)
            self.full_name.setText(user.full_name)
            self.role.setCurrentText(user.role)
            self.active.setChecked(user.is_active)
            self.waitress.setChecked(bool(getattr(user, 'is_waitress', False)))
            self.commission_rate.setValue(float(getattr(user, 'commission_rate', 0) or 0))
            self.password.setPlaceholderText(t('Laisser vide pour ne pas changer'))

    def _sync_commission_visibility(self, checked: bool) -> None:
        self.commission_row_label.setVisible(bool(checked))
        self.commission_rate.setVisible(bool(checked))

    def _save(self) -> None:
        if not self.username.text().strip():
            warn(self, t("Le nom d'utilisateur est obligatoire."))
            return
        if not self.user and (not self.password.text()):
            warn(self, t('Le mot de passe est obligatoire.'))
            return
        if self.password.text():
            try:
                validate_password(self.password.text())
            except ValueError as exc:
                warn(self, str(exc))
                return
        self.data = {
            'username': self.username.text().strip(),
            'full_name': self.full_name.text().strip(),
            'password': self.password.text(),
            'role': self.role.currentText(),
            'is_active': self.active.isChecked(),
            'is_waitress': self.waitress.isChecked(),
            'commission_rate': self.commission_rate.value(),
        }
        self.accept()

ROLE_COLORS = {'Administrateur': ('#ede9fe', '#5b21b6'), 'Gestionnaire': ('#dbeafe', '#1e40af'), 'Caissier': ('#dcfce7', '#166534')}
ABILITIES = [
    (perms.SELL, 'Vendre et imprimer les tickets'),
    (perms.APPLY_DISCOUNT, 'Faire des remises'),
    (perms.SELL_ON_CREDIT, 'Vendre à crédit'),
    (perms.MANAGE_CLIENTS, 'Gérer les clients'),
    (perms.MANAGE_CLIENT_DEBTS, 'Encaisser les dettes des clients'),
    (perms.MANAGE_STOCK, 'Gérer le stock'),
    (perms.MANAGE_PRODUCTS, 'Créer et modifier les produits'),
    (perms.MANAGE_PRICES, 'Modifier les prix'),
    (perms.MANAGE_SUPPLIERS, 'Gérer les fournisseurs'),
    (perms.MANAGE_PURCHASES, 'Enregistrer des achats'),
    (perms.MANAGE_EXPENSES, 'Saisir des dépenses'),
    (perms.VIEW_REPORTS, 'Voir les rapports'),
    (perms.VIEW_PROFITS, 'Voir les bénéfices'),
    (perms.CANCEL_SALE, 'Annuler une vente'),
    (perms.VIEW_AUDIT, "Voir le journal d'audit"),
    (perms.MANAGE_SETTINGS, 'Modifier les paramètres'),
    (perms.MANAGE_USERS, 'Gérer les utilisateurs'),
]


def role_abilities(role: str) -> tuple[list[str], list[str]]:
    """(ce que le rôle permet, ce qu'il ne permet pas), en langage simple."""
    granted = perms.permissions_for(role)
    can, cannot = [], []
    for perm, label in ABILITIES:
        ok = perm in granted
        if perm == perms.CANCEL_SALE and not ok and perms.CANCEL_SALE_WITH_AUTH in granted:
            can.append('Annuler une vente (avec le mot de passe d\'un administrateur)')
            continue
        (can if ok else cannot).append(label)
    return can, cannot


def user_activity(user_id: int) -> tuple[int, float]:
    """Nombre de ventes et montant encaissé par l'utilisateur ce mois-ci."""
    start = date.today().replace(day=1)
    with session_scope() as session:
        row = session.execute(select(func.count(Sale.id), func.coalesce(func.sum(Sale.total), 0)).where(Sale.user_id == user_id, Sale.status == 'completed', Sale.date >= start)).one()
    return int(row[0] or 0), float(row[1] or 0)


class UsersPage(QWidget):
    HEADERS = ['Utilisateur', 'Nom complet', 'Rôle', 'Statut']
    FILTERS = [('Tous', None), ('Administrateurs', 'Administrateur'), ('Gestionnaires', 'Gestionnaire'), ('Caissiers', 'Caissier'), ('Inactifs', 'inactive')]

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._ids: list[int] = []
        self._users: list = []
        self._filter = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(page_title(t('Utilisateurs')))
        header.addStretch()
        add = QPushButton(t('+ Nouvel utilisateur'))
        add.setObjectName('Primary')
        add.clicked.connect(self._add)
        header.addWidget(add)
        layout.addLayout(header)
        cards = QHBoxLayout()
        self.k_all, self.k_active, self.k_admin = QLabel(), QLabel(), QLabel()
        for k in (self.k_all, self.k_active, self.k_admin):
            k.setTextFormat(Qt.TextFormat.RichText)
            k.setMinimumHeight(44)
            cards.addWidget(make_card(k), 1)
        layout.addLayout(cards)
        body = QHBoxLayout()
        body.setSpacing(12)
        left_w = QWidget()
        left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(t('Rechercher un utilisateur…'))
        self.search.textChanged.connect(lambda _=None: self._render())
        left.addWidget(self.search)
        bar = QHBoxLayout()
        self.chips: list[QPushButton] = []
        for label, key in self.FILTERS:
            chip = QPushButton(t(label))
            chip.setCheckable(True)
            chip.setChecked(key is None)
            chip.setStyleSheet('QPushButton:checked { background: #2563eb; color: #ffffff; border-color: #2563eb; }')
            chip.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self.chips.append(chip)
            bar.addWidget(chip)
        bar.addStretch(1)
        left.addLayout(bar)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels([t(h) for h in self.HEADERS])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        enable_multi(self.table)
        self.table.doubleClicked.connect(self._edit)
        self.table.itemSelectionChanged.connect(self._show_detail)
        left.addWidget(self.table, 1)
        body.addWidget(make_card(left_w), 3)
        right_w = QWidget()
        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(8)
        self.detail = QLabel()
        self.detail.setTextFormat(Qt.TextFormat.RichText)
        self.detail.setWordWrap(True)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignTop)
        right.addWidget(self.detail, 1)
        row = QHBoxLayout()
        self.btn_edit = QPushButton(t('Modifier'))
        self.btn_edit.clicked.connect(self._edit)
        self.btn_pwd = QPushButton(t('Nouveau mot de passe'))
        self.btn_pwd.clicked.connect(self._new_password)
        self.btn_toggle = QPushButton(t('Désactiver'))
        self.btn_toggle.clicked.connect(self._toggle_active)
        self.btn_delete = QPushButton(t('Supprimer'))
        self.btn_delete.setObjectName('DangerOutline')
        self.btn_delete.clicked.connect(self._delete)
        for b in (self.btn_edit, self.btn_pwd, self.btn_toggle, self.btn_delete):
            row.addWidget(b)
        right.addLayout(row)
        body.addWidget(make_card(right_w), 2)
        layout.addLayout(body, 1)

    def _guard_admin(self) -> bool:
        if not self.state.can(perms.MANAGE_USERS):
            warn(self, t('Seul un administrateur peut gérer les utilisateurs.'))
            return False
        return True

    def _set_filter(self, key) -> None:
        self._filter = key
        for chip, (_l, k) in zip(self.chips, self.FILTERS):
            chip.setChecked(k == key)
        self._render()

    def refresh(self) -> None:
        self._users = list(AuthService.list_users())
        active = [u for u in self._users if u.is_active]
        admins = [u for u in active if u.role == perms.ROLE_ADMIN]
        for lab, title, val in ((self.k_all, 'Utilisateurs', len(self._users)), (self.k_active, 'Actifs', len(active)), (self.k_admin, 'Administrateurs', len(admins))):
            lab.setText(f"<span style='color:#64748b'>{t(title)}</span><br><b style='font-size:18px'>{val}</b>")
        self._render()

    def _render(self) -> None:
        keep = self._selected_id()
        needle = self.search.text().strip().lower()
        rows = []
        for u in self._users:
            if self._filter == 'inactive':
                if u.is_active:
                    continue
            elif self._filter and u.role != self._filter:
                continue
            if needle and needle not in u.username.lower() and needle not in (u.full_name or '').lower():
                continue
            rows.append(u)
        self._ids = [u.id for u in rows]
        self.table.setRowCount(len(rows))
        for r, u in enumerate(rows):
            role = QTableWidgetItem(u.role)
            bg, fg = ROLE_COLORS.get(u.role, ('#f1f5f9', '#475569'))
            role.setBackground(QBrush(QColor(bg if u.is_active else '#f1f5f9')))
            role.setForeground(QBrush(QColor(fg if u.is_active else '#64748b')))
            role.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            name = QTableWidgetItem(u.username)
            f = name.font()
            f.setBold(True)
            name.setFont(f)
            items = [name, QTableWidgetItem(u.full_name or ''), role, QTableWidgetItem('● Actif' if u.is_active else '○ Désactivé')]
            for c, it in enumerate(items):
                if not u.is_active and c != 2:
                    it.setForeground(QBrush(QColor('#94a3b8')))
                self.table.setItem(r, c, it)
        if keep in self._ids:
            self.table.selectRow(self._ids.index(keep))
        elif rows:
            self.table.selectRow(0)
        self._show_detail()

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._ids):
            return None
        return self._ids[row]

    def _selected_user(self):
        uid = self._selected_id()
        return next((u for u in self._users if u.id == uid), None)

    def _show_detail(self) -> None:
        u = self._selected_user()
        for b in (self.btn_edit, self.btn_pwd, self.btn_toggle, self.btn_delete):
            b.setEnabled(u is not None)
        if not u:
            self.detail.setText(f"<span style='color:#64748b'>{t('Sélectionnez un utilisateur pour voir sa fiche.')}</span>")
            return
        bg, fg = ROLE_COLORS.get(u.role, ('#f1f5f9', '#475569'))
        status = t('● Actif') if u.is_active else t('○ Désactivé')
        count, total = user_activity(u.id)
        currency = settings_service.get_currency()
        can, cannot = role_abilities(u.role)
        if not cannot:
            can = ['Accès complet à toutes les pages et à tous les réglages']
        li = lambda items, color: ''.join(f"<li style='color:{color}'>{t(x)}</li>" for x in items) or f"<li style='color:#94a3b8'>{t('Rien')}</li>"
        self.detail.setText(
            f"<div style='font-size:17px'><b>{u.full_name or u.username}</b></div>"
            f"<div style='color:#64748b'>{u.username} · <span style='background:{bg};color:{fg}'>&nbsp;{u.role}&nbsp;</span> · {status}</div><br>"
            f"<b>{t('Activité ce mois')}</b><br>{count} {t('vente(s)')} · {format_money(total, currency)}<br><br>"
            f"<b>{t('Ce que ce rôle permet')}</b><ul style='margin-top:2px'>{li(can, '#0f172a')}</ul>"
            + (f"<b>{t('Ce que ce rôle ne permet pas')}</b><ul style='margin-top:2px'>{li(cannot, '#64748b')}</ul>" if cannot else ''))
        self.btn_toggle.setText(t('Désactiver') if u.is_active else t('Réactiver'))

    def _audit(self) -> dict:
        return {'audit_user_id': self.state.user_id, 'audit_username': getattr(self.state.current_user, 'username', '')}

    def _add(self) -> None:
        if not self._guard_admin():
            return
        dialog = UserDialog(parent=self)
        if dialog.exec() and dialog.data:
            try:
                AuthService.create_user(dialog.data['username'], dialog.data['password'], dialog.data['full_name'], dialog.data['role'], is_waitress=dialog.data.get('is_waitress', False), commission_rate=dialog.data.get('commission_rate', 0), **self._audit())
            except ValueError as exc:
                warn(self, str(exc))
                return
            self.refresh()

    def _edit(self, *_a) -> None:
        if not self._guard_admin():
            return
        user = self._selected_user()
        if not user:
            warn(self, t('Sélectionnez un utilisateur.'))
            return
        dialog = UserDialog(user=user, parent=self)
        if dialog.exec() and dialog.data:
            try:
                AuthService.update_user(user.id, full_name=dialog.data['full_name'], role=dialog.data['role'], is_active=dialog.data['is_active'], is_waitress=dialog.data.get('is_waitress', False), commission_rate=dialog.data.get('commission_rate', 0), password=dialog.data['password'] or None, **self._audit())
            except ValueError as exc:
                warn(self, str(exc))
                return
            self.refresh()

    def _new_password(self) -> None:
        if not self._guard_admin():
            return
        user = self._selected_user()
        if not user:
            return
        text, ok = QInputDialog.getText(self, t('Nouveau mot de passe'), f"{t('Nouveau mot de passe pour')} {user.username}", QLineEdit.EchoMode.Password)
        if not ok or not text:
            return
        try:
            AuthService.update_user(user.id, password=text, **self._audit())
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()

    def _toggle_active(self) -> None:
        if not self._guard_admin():
            return
        user = self._selected_user()
        if not user:
            return
        if user.id == self.state.user_id and user.is_active:
            warn(self, t('Vous ne pouvez pas désactiver votre propre compte.'))
            return
        try:
            AuthService.update_user(user.id, is_active=not user.is_active, **self._audit())
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.refresh()

    def _delete(self) -> None:
        if not self._guard_admin():
            return
        rows = [r for r in selected_rows(self.table) if r < len(self._ids)]
        if not rows:
            warn(self, t('Sélectionnez un utilisateur.'))
            return
        if self.state.user_id in [self._ids[r] for r in rows]:
            warn(self, t('Vous ne pouvez pas supprimer votre propre compte.'))
            return
        items = [(self._ids[r], self.table.item(r, 0).text()) for r in rows]
        run_batch(self, t('Supprimer {n} utilisateur(s) ?'), items, lambda uid: AuthService.delete_user(uid, **self._audit()), t('utilisateur(s) supprimé(s)'))
        self.refresh()
