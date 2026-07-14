"""Fenêtre principale : barre latérale de navigation + pages empilées."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.services import settings_service
from app.ui.pages.categories_page import CategoriesPage
from app.ui.pages.clients_page import ClientsPage
from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.expenses_page import ExpensesPage
from app.ui.pages.pos_page import POSPage
from app.ui.pages.products_page import ProductsPage
from app.ui.pages.reports_page import ReportsPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.stock_page import StockPage
from app.ui.pages.suppliers_page import SuppliersPage
from app.ui.pages.users_page import UsersPage
from app.ui.state import AppState

# (libellé, icône, classe de page, réservé aux admins)
NAV_ITEMS = [
    ("Tableau de bord", "📊", DashboardPage, False),
    ("Caisse", "🛒", POSPage, False),
    ("Produits", "📦", ProductsPage, False),
    ("Catégories", "🏷️", CategoriesPage, False),
    ("Stock", "📥", StockPage, False),
    ("Clients", "👥", ClientsPage, False),
    ("Fournisseurs", "🚚", SuppliersPage, False),
    ("Dépenses", "💸", ExpensesPage, False),
    ("Rapports", "📈", ReportsPage, False),
    ("Utilisateurs", "🔐", UsersPage, True),
    ("Paramètres", "⚙️", SettingsPage, False),
]


class MainWindow(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setWindowTitle("Gestion Commerciale")
        self.resize(1280, 800)

        self.pages: list[QWidget] = []
        self._nav_buttons: list[QPushButton] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self._build_pages()
        self.state.data_changed.connect(self._refresh_current)
        self.select_page(0)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(240)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(6)

        shop = settings_service.get_shop_info()
        title = QLabel(shop.name or "Gestion")
        title.setObjectName("SidebarTitle")
        title.setWordWrap(True)
        subtitle = QLabel(shop.shop_type or "Commerce")
        subtitle.setObjectName("SidebarSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        self._title_label = title
        self._subtitle_label = subtitle

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)

        for index, (label, icon, _page, admin_only) in enumerate(NAV_ITEMS):
            if admin_only and not self.state.is_admin:
                self._nav_buttons.append(None)
                continue
            button = QPushButton(f"{icon}  {label}")
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, i=index: self.select_page(i))
            layout.addWidget(button)
            self._nav_group.addButton(button)
            self._nav_buttons.append(button)

        layout.addStretch()

        user = self.state.current_user
        self._user_label = QLabel(
            f"👤 {user.full_name or user.username}\n{user.role}" if user else ""
        )
        self._user_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        layout.addWidget(self._user_label)

        logout = QPushButton("Se déconnecter")
        logout.setObjectName("NavButton")
        logout.clicked.connect(self._logout)
        layout.addWidget(logout)

        version = QLabel(f"v{__version__}")
        version.setStyleSheet("color: #475569; font-size: 11px;")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)
        return sidebar

    def _build_pages(self) -> None:
        for label, _icon, page_class, admin_only in NAV_ITEMS:
            if admin_only and not self.state.is_admin:
                self.pages.append(None)
                continue
            page = page_class(self.state)
            self.pages.append(page)
            self.stack.addWidget(page)

    def select_page(self, index: int) -> None:
        page = self.pages[index] if index < len(self.pages) else None
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        button = self._nav_buttons[index]
        if button:
            button.setChecked(True)
        if hasattr(page, "refresh"):
            page.refresh()

    def _refresh_current(self) -> None:
        current = self.stack.currentWidget()
        if current and hasattr(current, "refresh"):
            current.refresh()
        shop = settings_service.get_shop_info()
        self._title_label.setText(shop.name or "Gestion")
        self._subtitle_label.setText(shop.shop_type or "Commerce")

    def _logout(self) -> None:
        self.state.auth.logout()
        self.close()
        # Redémarrage du flux de connexion géré par l'application principale.
        from app.ui.app import restart_login

        restart_login()
