"""Page des paramètres : commerce, apparence, tickets, sauvegarde, journal."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
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
from app.ui.widgets.helpers import (
    confirm,
    error,
    info,
    make_card,
    page_title,
    section_title,
    warn,
)
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
        self.printer.setPlaceholderText(
            "Nom d'imprimante (Windows) ou chemin (ex: /dev/usb/lp0) — vide = par défaut"
        )
        self.footer = QLineEdit()

        # Réglages d'avance papier et de coupe (dépannage « le ticket ne coupe
        # pas / ne sort pas entièrement »).
        self.feed_lines = QSpinBox()
        self.feed_lines.setRange(0, 20)
        self.feed_lines.setSuffix(" lignes d'avance avant coupe")
        self.cut_mode = QComboBox()
        self.cut_mode.addItem("Coupe complète", "full")
        self.cut_mode.addItem("Coupe partielle", "partial")
        self.cut_mode.addItem("Pas de coupe (déchirer)", "none")

        form.addRow("Thème", self.theme)
        form.addRow("Format du ticket", self.ticket_format)
        form.addRow("Imprimante", self.printer)
        form.addRow("Avance papier", self.feed_lines)
        form.addRow("Coupe", self.cut_mode)
        form.addRow("Message du ticket", self.footer)
        outer.addWidget(make_card(form_widget))

        actions = QHBoxLayout()
        save = QPushButton("Appliquer")
        save.setObjectName("Primary")
        save.clicked.connect(self._save_appearance)
        test_print = QPushButton("Imprimer une page de test")
        test_print.clicked.connect(self._print_test_page)
        actions.addWidget(save)
        actions.addWidget(test_print)
        actions.addStretch()
        outer.addLayout(actions)
        outer.addStretch()
        return wrap

    def _print_test_page(self) -> None:
        # Applique d'abord les réglages saisis pour tester la configuration réelle.
        self._save_appearance(silent=True)
        from app.printers import thermal_printer

        result = thermal_printer.print_test_page()
        if result.printed:
            info(self, f"Page de test envoyée.\n{result.message}", "Test d'impression")
        else:
            warn(
                self,
                f"Impression de test impossible.\n{result.message}\n\n"
                "Vérifiez le nom de l'imprimante et les réglages ci-dessus.",
                "Test d'impression",
            )

    def _save_appearance(self, silent: bool = False) -> None:
        dark = self.theme.currentText() == "Sombre"
        self.state.set_dark(dark)
        settings_service.set_setting("ticket_format", self.ticket_format.currentText())
        settings_service.set_setting("printer_name", self.printer.text().strip())
        settings_service.set_setting("ticket_feed_lines", str(self.feed_lines.value()))
        settings_service.set_setting("ticket_cut_mode", self.cut_mode.currentData())
        settings_service.save_shop_info(ticket_footer=self.footer.text().strip())
        if not silent:
            info(self, "Préférences appliquées.")

    # --- Onglet sauvegarde -------------------------------------------------
    def _build_backup_tab(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setSpacing(12)

        # Bloc d'information sur la dernière sauvegarde.
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(4, 4, 4, 4)
        info_layout.addWidget(section_title("Dernière sauvegarde"))
        self.last_backup_label = QLabel("Aucune sauvegarde pour le moment.")
        self.last_backup_label.setWordWrap(True)
        info_layout.addWidget(self.last_backup_label)
        layout.addWidget(make_card(info_widget))

        # Actions principales.
        buttons = QHBoxLayout()
        create = QPushButton("Créer une sauvegarde")
        create.setObjectName("Primary")
        create.clicked.connect(self._create_backup)
        create_here = QPushButton("Sauvegarde rapide (dossier par défaut)")
        create_here.clicked.connect(self._create_backup_default)
        restore_file = QPushButton("Restaurer une sauvegarde…")
        restore_file.setObjectName("Danger")
        restore_file.clicked.connect(self._restore_from_file)
        buttons.addWidget(create)
        buttons.addWidget(create_here)
        buttons.addWidget(restore_file)
        buttons.addStretch()
        layout.addLayout(buttons)

        # Options de sauvegarde automatique et de rétention.
        auto_widget = QWidget()
        auto_form = QFormLayout(auto_widget)
        auto_form.setSpacing(10)
        self.auto_enabled = QCheckBox("Activer la sauvegarde automatique")
        self.auto_frequency = QComboBox()
        self.auto_frequency.addItems(["Quotidienne", "Hebdomadaire", "Mensuelle"])
        self.retention = QSpinBox()
        self.retention.setRange(1, 200)
        self.retention.setValue(backup_service.DEFAULT_RETENTION)
        self.retention.setSuffix(" sauvegardes conservées")
        auto_form.addRow(self.auto_enabled)
        auto_form.addRow("Fréquence", self.auto_frequency)
        auto_form.addRow("Rétention", self.retention)
        save_auto = QPushButton("Enregistrer les options")
        save_auto.setObjectName("Primary")
        save_auto.clicked.connect(self._save_auto_options)
        auto_form.addRow(save_auto)
        layout.addWidget(make_card(auto_widget))

        # Liste des sauvegardes du dossier géré.
        layout.addWidget(section_title("Sauvegardes disponibles"))
        self.backup_table = QTableWidget(0, 3)
        self.backup_table.setHorizontalHeaderLabels(["Fichier", "Date", "Taille"])
        self.backup_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.backup_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.backup_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.backup_table)

        table_actions = QHBoxLayout()
        table_actions.addStretch()
        restore_selected = QPushButton("Restaurer la sélection")
        restore_selected.setObjectName("Danger")
        restore_selected.clicked.connect(self._restore_selected)
        table_actions.addWidget(restore_selected)
        layout.addLayout(table_actions)
        return wrap

    def _default_documents_dir(self) -> str:
        documents = Path.home() / "Documents"
        return str(documents if documents.exists() else Path.home())

    def _create_backup(self) -> None:
        """Crée une sauvegarde à l'emplacement choisi par l'utilisateur."""
        default_name = f"Sauvegarde_{__import__('datetime').datetime.now():%Y-%m-%d_%H-%M-%S}.zip"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Enregistrer la sauvegarde",
            str(Path(self._default_documents_dir()) / default_name),
            "Archives ZIP (*.zip)",
        )
        if not path:
            return
        target = Path(path)
        try:
            result = backup_service.create_full_backup(
                destination_dir=target.parent, manual=True
            )
            # Renomme si l'utilisateur a choisi un nom personnalisé.
            if target.name and target.name != result.name:
                final = target.with_suffix(".zip")
                result.replace(final)
                result = final
        except backup_service.BackupError as exc:
            error(self, str(exc), "Sauvegarde")
            return
        audit_service.log_action(
            "Sauvegarde", "Backup", str(result),
            self.state.user_id, getattr(self.state.current_user, "username", ""),
        )
        info(self, f"Sauvegarde créée :\n{result}")
        self._reload_backups()

    def _create_backup_default(self) -> None:
        """Sauvegarde rapide dans le dossier géré (BACKUP_DIR)."""
        try:
            result = backup_service.create_full_backup(manual=True)
        except backup_service.BackupError as exc:
            error(self, str(exc), "Sauvegarde")
            return
        audit_service.log_action(
            "Sauvegarde", "Backup", str(result),
            self.state.user_id, getattr(self.state.current_user, "username", ""),
        )
        info(self, f"Sauvegarde créée :\n{result}")
        self._reload_backups()

    def _perform_restore(self, zip_path) -> None:
        if not self.state.is_admin:
            warn(self, "Seul un administrateur peut restaurer une sauvegarde.")
            return
        if not confirm(
            self,
            "Restaurer cette sauvegarde remplacera TOUTES les données actuelles "
            "(base, logos, tickets, exports).\n\nUne sauvegarde de sécurité de "
            "l'état actuel sera créée automatiquement.\n\nContinuer ?",
        ):
            return
        try:
            backup_service.restore_backup(zip_path)
        except backup_service.BackupError as exc:
            error(self, str(exc), "Restauration")
            return
        audit_service.log_action(
            "Restauration", "Backup", str(zip_path),
            self.state.user_id, getattr(self.state.current_user, "username", ""),
        )
        info(
            self,
            "Restauration effectuée avec succès.\n\n"
            "Veuillez redémarrer l'application pour appliquer les changements.",
            "Restauration terminée",
        )
        self._reload_backups()

    def _restore_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choisir une sauvegarde à restaurer",
            self._default_documents_dir(),
            "Archives ZIP (*.zip)",
        )
        if path:
            self._perform_restore(path)

    def _restore_selected(self) -> None:
        row = self.backup_table.currentRow()
        if row < 0 or row >= len(self._backup_paths):
            warn(self, "Sélectionnez une sauvegarde dans la liste.")
            return
        self._perform_restore(self._backup_paths[row])

    def _save_auto_options(self) -> None:
        settings_service.set_setting(
            backup_service.SETTING_AUTO_ENABLED,
            "1" if self.auto_enabled.isChecked() else "0",
        )
        settings_service.set_setting(
            backup_service.SETTING_AUTO_FREQUENCY,
            self.auto_frequency.currentText().lower(),
        )
        settings_service.set_setting(
            backup_service.SETTING_RETENTION, str(self.retention.value())
        )
        backup_service.prune_backups(self.retention.value())
        info(self, "Options de sauvegarde enregistrées.")
        self._reload_backups()

    def _load_auto_options(self) -> None:
        self.auto_enabled.setChecked(backup_service.is_auto_enabled())
        self.auto_frequency.setCurrentText(backup_service.get_frequency().capitalize())
        self.retention.setValue(backup_service.get_retention())

    def _reload_backups(self) -> None:
        infos = backup_service.backup_infos()
        self._backup_paths = [i.path for i in infos]
        self.backup_table.setRowCount(len(infos))
        for row, item in enumerate(infos):
            self.backup_table.setItem(row, 0, QTableWidgetItem(item.path.name))
            self.backup_table.setItem(
                row, 1, QTableWidgetItem(format_datetime(item.created_at))
            )
            self.backup_table.setItem(row, 2, QTableWidgetItem(item.size_human))

        last = backup_service.latest_backup()
        if last:
            self.last_backup_label.setText(
                f"Date : {format_datetime(last.created_at)}\n"
                f"Emplacement : {last.path}\n"
                f"Taille : {last.size_human}"
            )
        else:
            self.last_backup_label.setText("Aucune sauvegarde pour le moment.")

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
            self._load_auto_options()
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
        try:
            self.feed_lines.setValue(int(settings_service.get_setting("ticket_feed_lines", "5")))
        except (TypeError, ValueError):
            self.feed_lines.setValue(5)
        cut_index = self.cut_mode.findData(
            settings_service.get_setting("ticket_cut_mode", "full")
        )
        if cut_index >= 0:
            self.cut_mode.setCurrentIndex(cut_index)
        self._load_auto_options()
        self._reload_backups()
