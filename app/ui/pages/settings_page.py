"""Page des paramètres : commerce, apparence, tickets, sauvegarde, journal."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.services import audit_service, backup_service, settings_service
from app.ui.setup_wizard import CURRENCIES, SHOP_TYPES
from app.ui.state import AppState
from app.ui.widgets.helpers import confirm, info, make_card, page_title, warn
from app.utils.helpers import format_datetime


class SettingsPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._logo_path = ""
        self._backup_paths: list[Path] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(page_title("Paramètres"))

        tabs = QTabWidget()
        tabs.addTab(self._build_shop_tab(), "Commerce")
        tabs.addTab(self._build_appearance_tab(), "Apparence & Ticket")
        tabs.addTab(self._build_backup_tab(), "Sauvegarde")
        tabs.addTab(self._build_audit_tab(), "Journal d'audit")
        tabs.currentChanged.connect(self._on_tab)
        layout.addWidget(tabs)

    # --- Onglet commerce ---------------------------------------------------
    def _build_shop_tab(self) -> QWidget:
        wrap = QWidget()
        outer = QVBoxLayout(wrap)
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setSpacing(10)

        self.name = QLineEdit()
        self.address = QLineEdit()
        self.phone = QLineEdit()
        self.email = QLineEdit()
        self.currency = QComboBox()
        self.currency.setEditable(True)
        self.currency.addItems(CURRENCIES)
        self.shop_type = QComboBox()
        self.shop_type.addItems(SHOP_TYPES)
        self.vat = QDoubleSpinBox()
        self.vat.setRange(0, 100)
        self.vat.setDecimals(2)
        self.vat.setSuffix(" %")

        logo_row = QHBoxLayout()
        self.logo_label = QLineEdit()
        self.logo_label.setReadOnly(True)
        logo_button = QPushButton("Choisir…")
        logo_button.clicked.connect(self._pick_logo)
        logo_row.addWidget(self.logo_label)
        logo_row.addWidget(logo_button)

        form.addRow("Nom du commerce", self.name)
        form.addRow("Adresse", self.address)
        form.addRow("Téléphone", self.phone)
        form.addRow("Email", self.email)
        form.addRow("Devise", self.currency)
        form.addRow("Type de commerce", self.shop_type)
        form.addRow("TVA", self.vat)
        form.addRow("Logo", logo_row)
        outer.addWidget(make_card(form_widget))

        save = QPushButton("Enregistrer les informations")
        save.setObjectName("Primary")
        save.clicked.connect(self._save_shop)
        outer.addWidget(save)
        outer.addStretch()
        return wrap

    def _pick_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir un logo", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self._logo_path = path
            self.logo_label.setText(path)

    def _save_shop(self) -> None:
        logo_stored = self.logo_label.text()
        if self._logo_path:
            config.ensure_directories()
            dest = config.LOGO_DIR / f"logo{Path(self._logo_path).suffix}"
            try:
                shutil.copy2(self._logo_path, dest)
                logo_stored = str(dest)
            except OSError:
                logo_stored = self._logo_path
        settings_service.save_shop_info(
            name=self.name.text().strip(),
            address=self.address.text().strip(),
            phone=self.phone.text().strip(),
            email=self.email.text().strip(),
            currency=self.currency.currentText().strip() or "FCFA",
            shop_type=self.shop_type.currentText(),
            vat_rate=self.vat.value(),
            logo_path=logo_stored,
            is_configured=True,
        )
        audit_service.log_action(
            "Paramètres commerce", "ShopInfo", "",
            self.state.user_id, getattr(self.state.current_user, "username", ""),
        )
        info(self, "Informations enregistrées.")
        self.state.notify_data_changed()

    # --- Onglet apparence / ticket ----------------------------------------
    def _build_appearance_tab(self) -> QWidget:
        wrap = QWidget()
        outer = QVBoxLayout(wrap)
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setSpacing(10)

        self.theme = QComboBox()
        self.theme.addItems(["Clair", "Sombre"])
        self.ticket_format = QComboBox()
        self.ticket_format.addItems(["80mm", "58mm"])
        self.printer = QLineEdit()
        self.printer.setPlaceholderText("Nom / chemin de l'imprimante (ex: /dev/usb/lp0)")
        self.footer = QLineEdit()

        form.addRow("Thème", self.theme)
        form.addRow("Format du ticket", self.ticket_format)
        form.addRow("Imprimante", self.printer)
        form.addRow("Message du ticket", self.footer)
        outer.addWidget(make_card(form_widget))

        save = QPushButton("Appliquer")
        save.setObjectName("Primary")
        save.clicked.connect(self._save_appearance)
        outer.addWidget(save)
        outer.addStretch()
        return wrap

    def _save_appearance(self) -> None:
        dark = self.theme.currentText() == "Sombre"
        self.state.set_dark(dark)
        settings_service.set_setting("ticket_format", self.ticket_format.currentText())
        settings_service.set_setting("printer_name", self.printer.text().strip())
        settings_service.save_shop_info(ticket_footer=self.footer.text().strip())
        info(self, "Préférences appliquées.")

    # --- Onglet sauvegarde -------------------------------------------------
    def _build_backup_tab(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)

        buttons = QHBoxLayout()
        create = QPushButton("Sauvegarde manuelle")
        create.setObjectName("Primary")
        create.clicked.connect(self._create_backup)
        restore = QPushButton("Restaurer la sélection")
        restore.setObjectName("Danger")
        restore.clicked.connect(self._restore_backup)
        buttons.addWidget(create)
        buttons.addWidget(restore)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.backup_table = QTableWidget(0, 2)
        self.backup_table.setHorizontalHeaderLabels(["Fichier", "Date"])
        self.backup_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.backup_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.backup_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.backup_table)
        return wrap

    def _create_backup(self) -> None:
        path = backup_service.create_backup(manual=True)
        info(self, f"Sauvegarde créée :\n{path}")
        self._reload_backups()

    def _restore_backup(self) -> None:
        row = self.backup_table.currentRow()
        if row < 0 or row >= len(self._backup_paths):
            warn(self, "Sélectionnez une sauvegarde.")
            return
        if not self.state.is_admin:
            warn(self, "Seul un administrateur peut restaurer une sauvegarde.")
            return
        if confirm(
            self,
            "Restaurer cette sauvegarde remplacera les données actuelles.\n"
            "Redémarrez l'application après la restauration. Continuer ?",
        ):
            backup_service.restore_backup(self._backup_paths[row])
            info(self, "Restauration effectuée. Veuillez redémarrer l'application.")

    def _reload_backups(self) -> None:
        self._backup_paths = backup_service.list_backups()
        self.backup_table.setRowCount(len(self._backup_paths))
        for row, path in enumerate(self._backup_paths):
            from datetime import datetime

            moment = datetime.fromtimestamp(path.stat().st_mtime)
            self.backup_table.setItem(row, 0, QTableWidgetItem(path.name))
            self.backup_table.setItem(row, 1, QTableWidgetItem(format_datetime(moment)))

    # --- Onglet journal ----------------------------------------------------
    def _build_audit_tab(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        self.audit_table = QTableWidget(0, 4)
        self.audit_table.setHorizontalHeaderLabels(["Date", "Utilisateur", "Action", "Détails"])
        self.audit_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.audit_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.audit_table)
        return wrap

    def _reload_audit(self) -> None:
        logs = audit_service.list_logs(limit=400)
        self.audit_table.setRowCount(len(logs))
        for row, log in enumerate(logs):
            self.audit_table.setItem(row, 0, QTableWidgetItem(format_datetime(log.date)))
            self.audit_table.setItem(row, 1, QTableWidgetItem(log.username))
            self.audit_table.setItem(row, 2, QTableWidgetItem(log.action))
            self.audit_table.setItem(row, 3, QTableWidgetItem(log.details))

    def _on_tab(self, index: int) -> None:
        if index == 2:
            self._reload_backups()
        elif index == 3:
            self._reload_audit()

    # --- Rafraîchissement --------------------------------------------------
    def refresh(self) -> None:
        shop = settings_service.get_shop_info()
        self.name.setText(shop.name)
        self.address.setText(shop.address)
        self.phone.setText(shop.phone)
        self.email.setText(shop.email)
        self.currency.setCurrentText(shop.currency)
        idx = self.shop_type.findText(shop.shop_type)
        if idx >= 0:
            self.shop_type.setCurrentIndex(idx)
        self.vat.setValue(float(shop.vat_rate or 0))
        self.logo_label.setText(shop.logo_path)
        self.footer.setText(shop.ticket_footer)
        self.theme.setCurrentText("Sombre" if self.state.dark else "Clair")
        self.ticket_format.setCurrentText(
            settings_service.get_setting("ticket_format", "80mm")
        )
        self.printer.setText(settings_service.get_setting("printer_name", ""))
        self._reload_backups()
