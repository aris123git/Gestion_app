"""Fenêtre principale : barre latérale de navigation + pages empilées."""

from __future__ import annotations

import logging
import time
from typing import Optional

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.services import permissions as perms
from app.services import settings_service
from app.ui.pages.assistant_page import AssistantPage
from app.ui.pages.categories_page import CategoriesPage
from app.ui.pages.clients_page import ClientsPage
from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.debts_page import DebtsPage
from app.ui.pages.expenses_page import ExpensesPage
from app.ui.pages.pos_page import POSPage
from app.ui.pages.products_page import ProductsPage
from app.ui.pages.purchases_page import PurchasesPage
from app.ui.pages.reports_page import ReportsPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.stock_page import StockPage
from app.ui.pages.suppliers_page import SuppliersPage
from app.ui.pages.users_page import UsersPage
from app.ui.dialogs.global_search_dialog import GlobalSearchDialog
from app.ui.responsive import (
    SIDEBAR_DRAWER,
    SIDEBAR_FULL,
    SIDEBAR_ICONS,
    SIDEBAR_WIDTH_FULL,
    SIDEBAR_WIDTH_ICONS,
    LayoutProfile,
)
from app.ui.state import AppState

logger = logging.getLogger(__name__)

# (libellé, icône, classe de page, permission requise ou None = tous les rôles)
NAV_ITEMS = [
    ("Caisse", "🛒", POSPage, perms.SELL),
    ("Tableau de bord", "📊", DashboardPage, perms.VIEW_DASHBOARD),
    ("Produits", "📦", ProductsPage, perms.VIEW_PRODUCTS),
    ("Catégories", "🏷️", CategoriesPage, perms.MANAGE_CATEGORIES),
    ("Stock", "📥", StockPage, perms.MANAGE_STOCK),
    ("Achats", "🧾", PurchasesPage, perms.MANAGE_PURCHASES),
    ("Clients", "👥", ClientsPage, perms.MANAGE_CLIENTS),
    ("Dettes", "💳", DebtsPage, perms.MANAGE_CLIENT_DEBTS),
    ("Fournisseurs", "🚚", SuppliersPage, perms.MANAGE_SUPPLIERS),
    ("Dépenses", "💸", ExpensesPage, perms.MANAGE_EXPENSES),
    ("Rapports", "📈", ReportsPage, perms.VIEW_REPORTS),
    ("Assistant", "💡", AssistantPage, perms.VIEW_ASSISTANT),
    ("Utilisateurs", "🔐", UsersPage, perms.MANAGE_USERS),
    ("Paramètres", "⚙️", SettingsPage, perms.MANAGE_SETTINGS),
]


class MainWindow(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setWindowTitle("Gestion Commerciale")
        self.setObjectName("MainWindow")
        # Compatible petits écrans ; le moteur responsive adapte ensuite.
        self.setMinimumSize(640, 480)
        self.resize(1920, 1080)
        self._idle_timeout_seconds = 120 * 60
        self._last_activity = time.monotonic()
        self._idle_logging_out = False
        self._drawer_open = False
        self._sidebar_mode = SIDEBAR_FULL

        self.pages: list[Optional[QWidget]] = []
        self._nav_buttons: list[Optional[QPushButton]] = []
        self._nav_meta: list[tuple[str, str]] = []  # (label, icon) par index NAV

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self._topbar = self._build_topbar()
        shell.addWidget(self._topbar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self._body_layout = body

        self._sidebar = self._build_sidebar()
        body.addWidget(self._sidebar)

        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        shell.addLayout(body, 1)

        self._build_pages()
        self.state.data_changed.connect(self._refresh_current)
        self.state.layout_changed.connect(self._apply_layout)
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(60_000)
        self._idle_timer.timeout.connect(self._check_idle_timeout)
        self._idle_timer.timeout.connect(self._refresh_auth_user)
        self._idle_timer.start()
        # Sauvegarde automatique périodique (vérifie l\'échéance sans bloquer).
        self._backup_timer = QTimer(self)
        self._backup_timer.setInterval(30 * 60_000)  # toutes les 30 minutes
        self._backup_timer.timeout.connect(self._run_periodic_backup)
        self._backup_timer.start()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self.select_page(0)
        # Premier calcul après affichage (resizeEvent le fera aussi).
        QTimer.singleShot(0, self._publish_viewport)

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(48)
        bar.hide()
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 4, 12, 4)
        row.setSpacing(10)

        self._menu_button = QPushButton("☰")
        self._menu_button.setObjectName("TopBarButton")
        self._menu_button.setFixedSize(40, 36)
        self._menu_button.setToolTip("Menu")
        self._menu_button.clicked.connect(self._toggle_drawer)
        row.addWidget(self._menu_button)

        self._topbar_title = QLabel("Gestion Commerciale")
        self._topbar_title.setObjectName("TopBarTitle")
        row.addWidget(self._topbar_title, 1)

        self._topbar_user = QLabel("")
        self._topbar_user.setObjectName("TopBarMeta")
        row.addWidget(self._topbar_user)
        return bar

    def _allowed(self, permission: Optional[str]) -> bool:
        if permission is None:
            return True
        return self.state.can(permission)

    def _run_periodic_backup(self) -> None:
        """Déclenche une sauvegarde automatique si la fréquence est échue."""
        try:
            from app.services import backup_service

            backup_service.run_startup_auto_backup()
        except Exception:
            logger.exception("Échec de la sauvegarde automatique périodique.")

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH_FULL)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(6)
        self._sidebar_layout = layout

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

        for index, (label, icon, _page, permission) in enumerate(NAV_ITEMS):
            self._nav_meta.append((label, icon))
            if not self._allowed(permission):
                self._nav_buttons.append(None)
                continue
            button = QPushButton(f"{icon}  {label}")
            button.setObjectName("NavButton")
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, i=index: self._on_nav_clicked(i))
            layout.addWidget(button)
            self._nav_group.addButton(button)
            self._nav_buttons.append(button)

        layout.addStretch()

        self._search_btn: Optional[QPushButton] = None
        if self._can_search():
            search_btn = QPushButton("🔎  Recherche")
            search_btn.setObjectName("NavButton")
            search_btn.setToolTip("Recherche")
            search_btn.setAccessibleName("Recherche")
            search_btn.clicked.connect(self._open_search)
            layout.addWidget(search_btn)
            self._search_btn = search_btn

        user = self.state.current_user
        self._user_label = QLabel(
            f"👤 {user.full_name or user.username}\n{user.role}" if user else ""
        )
        self._user_label.setObjectName("SidebarUser")
        layout.addWidget(self._user_label)

        logout = QPushButton("Se déconnecter")
        logout.setObjectName("NavButton")
        logout.setToolTip("Se déconnecter")
        logout.setAccessibleName("Se déconnecter")
        logout.clicked.connect(self._logout)
        layout.addWidget(logout)
        self._logout_btn = logout

        version = QLabel(f"v{__version__}")
        version.setObjectName("SidebarVersion")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)
        self._version_label = version
        return sidebar

    def _on_nav_clicked(self, index: int) -> None:
        self.select_page(index)
        if self._sidebar_mode == SIDEBAR_DRAWER:
            self._drawer_open = False
            self._sidebar.hide()

    def _toggle_drawer(self) -> None:
        self._drawer_open = not self._drawer_open
        self._sidebar.setVisible(self._drawer_open)
        if self._drawer_open:
            self._sidebar.setFixedWidth(SIDEBAR_WIDTH_FULL)
            self._set_nav_labels(full=True)

    def _publish_viewport(self) -> None:
        self.state.update_viewport(self.width(), self.height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._publish_viewport()

    def _apply_layout(self, profile: LayoutProfile) -> None:
        self.setProperty("widthMode", profile.width_mode)
        self.setProperty("heightMode", profile.height_mode)
        self.setProperty("density", profile.density)
        self.style().unpolish(self)
        self.style().polish(self)

        mode = profile.sidebar_mode
        self._sidebar_mode = mode

        if mode == SIDEBAR_DRAWER:
            self._topbar.show()
            shop = settings_service.get_shop_info()
            self._topbar_title.setText(shop.name or "Gestion Commerciale")
            user = self.state.current_user
            if user:
                self._topbar_user.setText(user.full_name or user.username)
            if not self._drawer_open:
                self._sidebar.hide()
            else:
                self._sidebar.show()
                self._sidebar.setFixedWidth(SIDEBAR_WIDTH_FULL)
                self._set_nav_labels(full=True)
        elif mode == SIDEBAR_ICONS:
            self._topbar.hide()
            self._drawer_open = False
            self._sidebar.show()
            self._sidebar.setFixedWidth(SIDEBAR_WIDTH_ICONS)
            self._set_nav_labels(full=False)
            margins = 8 if profile.density == "compact" else 10
            self._sidebar_layout.setContentsMargins(margins, 12, margins, 12)
        else:
            self._topbar.hide()
            self._drawer_open = False
            self._sidebar.show()
            self._sidebar.setFixedWidth(SIDEBAR_WIDTH_FULL)
            self._set_nav_labels(full=True)
            self._sidebar_layout.setContentsMargins(14, 18, 14, 18)

        # Densité : réduire un peu les marges sidebar en écran court.
        if profile.is_short and mode != SIDEBAR_DRAWER:
            self._sidebar_layout.setSpacing(4)

    def _set_nav_labels(self, *, full: bool) -> None:
        self._title_label.setVisible(full)
        self._subtitle_label.setVisible(full)
        self._user_label.setVisible(full)
        self._version_label.setVisible(full)
        for index, button in enumerate(self._nav_buttons):
            if button is None:
                continue
            label, icon = self._nav_meta[index]
            if full:
                button.setText(f"{icon}  {label}")
                button.setToolTip(label)
            else:
                button.setText(icon)
                button.setToolTip(label)
        if self._search_btn is not None:
            if full:
                self._search_btn.setText("🔎  Recherche")
            else:
                self._search_btn.setText("🔎")
                self._search_btn.setToolTip("Recherche")
        if full:
            self._logout_btn.setText("Se déconnecter")
        else:
            self._logout_btn.setText("🚪")
            self._logout_btn.setToolTip("Se déconnecter")

    def _build_pages(self) -> None:
        for label, _icon, page_class, permission in NAV_ITEMS:
            if not self._allowed(permission):
                self.pages.append(None)
                continue
            page = page_class(self.state)
            self.pages.append(page)
            self.stack.addWidget(page)

    def select_page(self, index: int, refresh_auth: bool = True) -> Optional[QWidget]:
        if refresh_auth and not self._refresh_auth_user():
            return None
        if index >= len(NAV_ITEMS):
            return None
        if not self._allowed(NAV_ITEMS[index][3]):
            return None
        page = self.pages[index] if index < len(self.pages) else None
        if page is None:
            return None
        self.stack.setCurrentWidget(page)
        button = self._nav_buttons[index]
        if button is not None:
            button.setChecked(True)
        label = NAV_ITEMS[index][0]
        self._topbar_title.setText(label)
        if hasattr(page, "refresh"):
            page.refresh()
        return page

    def _select_page_by_label(self, label: str) -> Optional[QWidget]:
        for index, (item_label, _icon, _page, _permission) in enumerate(NAV_ITEMS):
            if item_label == label:
                return self.select_page(index)
        return None

    def _refresh_current(self) -> None:
        if not self._refresh_auth_user():
            return
        current = self.stack.currentWidget()
        if current and hasattr(current, "refresh"):
            current.refresh()
        shop = settings_service.get_shop_info()
        self._title_label.setText(shop.name or "Gestion")
        self._subtitle_label.setText(shop.shop_type or "Commerce")
        if self._topbar.isVisible():
            self._topbar_title.setText(shop.name or "Gestion Commerciale")

    def _open_search(self) -> None:
        if not self._can_search():
            return
        dialog = GlobalSearchDialog(self)
        if dialog.exec() and dialog.selected_hit is not None:
            self._navigate_search_hit(dialog.selected_hit)

    def _navigate_search_hit(self, hit) -> None:
        page_label_by_kind = {
            "client": "Clients",
            "dette": "Clients",
            "produit": "Produits",
            "facture": "Rapports",
            "fournisseur": "Fournisseurs",
        }
        page = self._select_page_by_label(page_label_by_kind.get(hit.kind, ""))
        if page is None:
            return
        selector_by_kind = {
            "client": "select_client",
            "produit": "select_product",
            "facture": "select_sale",
            "fournisseur": "select_supplier",
        }
        selector_name = selector_by_kind.get(hit.kind)
        selector = getattr(page, selector_name, None) if selector_name else None
        if selector:
            selector(hit.entity_id)

    def _can_search(self) -> bool:
        return any(
            self.state.can(permission)
            for permission in (
                perms.VIEW_REPORTS,
                perms.VIEW_PRODUCTS,
                perms.MANAGE_PRODUCTS,
                perms.MANAGE_CLIENTS,
                perms.MANAGE_SUPPLIERS,
            )
        )

    def _refresh_auth_user(self) -> bool:
        """Recharge l\'utilisateur courant et invalide les accès retirés."""
        if self._idle_logging_out:
            return False
        had_user = self.state.current_user is not None
        user = self.state.auth.refresh_current_user()
        if had_user and user is None:
            self._idle_logging_out = True
            self._logout()
            return False
        if user and hasattr(self, "_user_label"):
            self._user_label.setText(f"👤 {user.full_name or user.username}\n{user.role}")
            if hasattr(self, "_topbar_user"):
                self._topbar_user.setText(user.full_name or user.username)
        for index, button in enumerate(self._nav_buttons):
            if button is not None:
                button.setEnabled(self._allowed(NAV_ITEMS[index][3]))
        current = self.stack.currentWidget()
        current_index = next(
            (i for i, page in enumerate(self.pages) if page is current),
            None,
        )
        if current_index is not None and not self._allowed(NAV_ITEMS[current_index][3]):
            for index, page in enumerate(self.pages):
                if page is not None and self._allowed(NAV_ITEMS[index][3]):
                    self.select_page(index, refresh_auth=False)
                    break
        return True

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() in {
            QEvent.Type.KeyPress,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.Wheel,
            QEvent.Type.TouchBegin,
        }:
            self._last_activity = time.monotonic()
        return super().eventFilter(obj, event)

    def _check_idle_timeout(self) -> None:
        if self._idle_logging_out or not self.state.current_user:
            return
        if time.monotonic() - self._last_activity >= self._idle_timeout_seconds:
            self._idle_logging_out = True
            self._logout()

    def _logout(self) -> None:
        self.state.auth.logout()
        self.close()
        # Redémarrage du flux de connexion géré par l\'application principale.
        from app.ui.app import restart_login

        restart_login()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # F11 : bascule plein écran / fenêtre. Échap : quitte le plein écran.
        if event.key() == Qt.Key.Key_F11:
            if self.isFullScreen():
                self.showNormal()
                self.resize(1280, 720)
            else:
                self.showFullScreen()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.showNormal()
            self.resize(1280, 720)
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._idle_timer.stop()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().closeEvent(event)
