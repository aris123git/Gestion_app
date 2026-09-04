"""Page des paramètres : commerce, apparence, tickets, sauvegarde, journal."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.services import audit_service, backup_service, permissions as perms, settings_service
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

# Libellé de l'entrée « imprimante par défaut du système » dans la liste.
DEFAULT_PRINTER_LABEL = "(Imprimante par défaut)"


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
        tabs.addTab(self._build_appearance_tab(), "Apparence du ticket")
        tabs.addTab(self._build_designs_tab(), "Designs des tickets")
        tabs.addTab(self._build_controls_tab(), "Contrôles caisse")
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
        self.fax = QLineEdit()
        self.fax.setPlaceholderText("Affiché sur le ticket facture (optionnel)")
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
        logo_type_btn = QPushButton("Logo du type")
        logo_type_btn.setToolTip(
            "Applique le logo fourni pour le type de commerce "
            "(poissonnerie, quincaillerie, pharmacie…)."
        )
        logo_type_btn.clicked.connect(self._apply_type_logo)
        logo_clear = QPushButton("Effacer")
        logo_clear.clicked.connect(self._clear_logo)
        logo_row.addWidget(self.logo_label, 1)
        logo_row.addWidget(logo_button)
        logo_row.addWidget(logo_type_btn)
        logo_row.addWidget(logo_clear)

        form.addRow("Nom du commerce", self.name)
        form.addRow("Adresse", self.address)
        form.addRow("Téléphone", self.phone)
        form.addRow("Fax", self.fax)
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

    def _apply_type_logo(self) -> None:
        """Associe le logo livré pour le type de commerce sélectionné."""
        from app.printers.shop_logos import default_logo_path

        shop_type = self.shop_type.currentText()
        path = default_logo_path(shop_type)
        if path is None:
            warn(
                self,
                f"Aucun logo fourni pour « {shop_type} ».",
                "Logo du type",
            )
            return
        self._logo_path = str(path)
        self.logo_label.setText(str(path))
        info(
            self,
            f"Logo « {shop_type} » sélectionné.\n"
            "Cliquez sur Enregistrer les informations pour confirmer.",
            "Logo du type",
        )

    def _clear_logo(self) -> None:
        self._logo_path = ""
        self.logo_label.clear()

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
        settings_service.set_setting("shop_fax", self.fax.text().strip())
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
        self.ticket_format.addItem("Ticket 80 mm", "80mm")
        self.ticket_format.addItem("Ticket 58 mm", "58mm")
        self.ticket_format.addItem("Facture papier (demi-A4)", "demi-A4")
        # Profil ESC/POS : largeur + codepage (accents FR).
        from app.printers.printer_profile import list_profiles

        self.printer_profile = QComboBox()
        self.printer_profile.setMinimumWidth(320)
        for profile in list_profiles():
            self.printer_profile.addItem(profile.label, profile.id)
        self.printer_profile.setToolTip(
            "Profil de l'imprimante thermique : largeur (58/80 mm) et codepage "
            "(CP850 recommandé pour le français). Si les accents sortent en "
            "chinois ou symboles, changez de profil puis « Test accents FR »."
        )
        self.printer_profile.currentIndexChanged.connect(self._on_printer_profile_changed)
        self.ticket_format.setToolTip(
            "Par défaut : ticket thermique. « Facture papier » = PDF 210×148,5 mm "
            "(A4 coupé en deux) pour imprimante bureau."
        )

        # Affichage caisse : texte agrandi pour serveur / précipitation.
        self.pos_large_text = QCheckBox(
            "Agrandir produits et prix en caisse (lecture rapide)"
        )
        self.pos_large_text.setToolTip(
            "Utile pour le serveur : voir rapidement quoi servir "
            "(noms et prix plus gros dans le catalogue et le panier)."
        )
        self.pos_text_size = QComboBox()
        self.pos_text_size.addItem("Grand", "large")
        self.pos_text_size.addItem("Très grand", "xlarge")
        self.pos_text_size.setEnabled(False)
        self.pos_large_text.toggled.connect(self.pos_text_size.setEnabled)

        # Liste déroulante des imprimantes détectées (éditable pour saisir un
        # chemin de périphérique si besoin) + bouton d'actualisation.
        self.printer = QComboBox()
        self.printer.setEditable(True)
        self.printer.setMinimumWidth(260)
        refresh_printers = QPushButton("Actualiser")
        refresh_printers.clicked.connect(lambda: self._reload_printers())
        printer_row = QHBoxLayout()
        printer_row.addWidget(self.printer, 1)
        printer_row.addWidget(refresh_printers)

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
        self.auto_print = QCheckBox(
            "Imprimer automatiquement (sinon : demander d'enregistrer d'abord)"
        )
        self.auto_print.setChecked(False)
        self.auto_print.setToolTip(
            "Par défaut, après une vente on propose d'enregistrer le ticket. "
            "Cochez seulement si vous voulez envoyer directement à l'imprimante. "
            "Si l'imprimante est éteinte, l'envoi est refusé (pas de file qui se "
            "vide au redémarrage)."
        )

        form.addRow("Thème", self.theme)
        form.addRow("Format du ticket", self.ticket_format)
        form.addRow("Profil imprimante", self.printer_profile)
        form.addRow("Lecture rapide caisse", self.pos_large_text)
        form.addRow("Taille du texte", self.pos_text_size)
        form.addRow("Imprimante", printer_row)
        form.addRow("Avance papier", self.feed_lines)
        form.addRow("Coupe", self.cut_mode)
        form.addRow("Après vente", self.auto_print)
        form.addRow("Message du ticket", self.footer)
        outer.addWidget(make_card(form_widget))

        designs_hint = QLabel(
            "Les designs visuels (Classique, Moderne, Bon serveur…) se "
            "choisissent dans l'onglet <b>Designs des tickets</b>. "
            "Le <b>profil imprimante</b> fixe le codepage ESC/POS "
            "(accents français) et la largeur en caractères."
        )
        designs_hint.setWordWrap(True)
        designs_hint.setStyleSheet("color: #64748b;")
        outer.addWidget(designs_hint)

        actions = QHBoxLayout()
        save = QPushButton("Appliquer")
        save.setObjectName("Primary")
        save.clicked.connect(self._save_appearance)
        test_print = QPushButton("Imprimer une page de test")
        test_print.clicked.connect(self._print_test_page)
        accent_test = QPushButton("Test accents FR")
        accent_test.setToolTip(
            "Imprime é è ê à â ù û î ï ô ö ç œ É À avec le codepage du profil. "
            "À faire avant une vraie facture."
        )
        accent_test.clicked.connect(self._print_encoding_test_page)
        purge = QPushButton("Vider la file d'attente")
        purge.setToolTip(
            "Annule les tickets en attente Windows (utile si plusieurs tickets "
            "sortent d'un coup après un rallumage)."
        )
        purge.clicked.connect(self._purge_printer_queue)
        actions.addWidget(save)
        actions.addWidget(test_print)
        actions.addWidget(accent_test)
        actions.addWidget(purge)
        actions.addStretch()
        outer.addLayout(actions)
        outer.addStretch()
        return wrap

    # --- Onglet designs des tickets ---------------------------------------
    def _build_designs_tab(self) -> QWidget:
        from app.printers.ticket.options import DENSITIES
        from app.printers.ticket.registry import CLIENT_DESIGNS, KITCHEN_DESIGNS
        from app.ui.widgets.ticket_design_card import TicketDesignCard

        wrap = QWidget()
        outer = QVBoxLayout(wrap)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setSpacing(14)

        intro = QLabel(
            "Choisissez indépendamment le design du <b>ticket client</b> et "
            "celui du <b>bon serveur / cuisine</b>. Les données restent "
            "identiques : seule la présentation change."
        )
        intro.setWordWrap(True)
        body_layout.addWidget(intro)

        # --- Ticket client ---
        client_box = QGroupBox("Ticket client")
        client_layout = QVBoxLayout(client_box)
        self._client_cards: dict[str, TicketDesignCard] = {}
        self._client_group = QButtonGroup(self)
        self._client_group.setExclusive(True)
        client_grid = QGridLayout()
        client_grid.setSpacing(10)
        for i, design in enumerate(CLIENT_DESIGNS):
            card = TicketDesignCard(design.id, design.label, design.description)
            card.selected.connect(self._on_client_design_selected)
            self._client_cards[design.id] = card
            self._client_group.addButton(card.radio)
            client_grid.addWidget(card, i // 4, i % 4)
        client_layout.addLayout(client_grid)
        body_layout.addWidget(client_box)

        # --- Bon serveur / cuisine ---
        kitchen_box = QGroupBox("Bon serveur / cuisine")
        kitchen_layout = QVBoxLayout(kitchen_box)
        self.kitchen_enabled = QCheckBox(
            "Activer le bon serveur / cuisine (impression séparée)"
        )
        self.kitchen_enabled.setChecked(True)
        self.kitchen_enabled.setToolTip(
            "Décochez pour masquer le bouton « Bon serveur » après une vente "
            "et désactiver l'impression cuisine."
        )
        self.kitchen_enabled.toggled.connect(self._on_kitchen_enabled_toggled)
        kitchen_layout.addWidget(self.kitchen_enabled)

        self._kitchen_cards_wrap = QWidget()
        kitchen_cards_layout = QVBoxLayout(self._kitchen_cards_wrap)
        kitchen_cards_layout.setContentsMargins(0, 0, 0, 0)
        self._kitchen_cards: dict[str, TicketDesignCard] = {}
        self._kitchen_group = QButtonGroup(self)
        self._kitchen_group.setExclusive(True)
        kitchen_grid = QGridLayout()
        kitchen_grid.setSpacing(10)
        for i, design in enumerate(KITCHEN_DESIGNS):
            card = TicketDesignCard(design.id, design.label, design.description)
            card.selected.connect(self._on_kitchen_design_selected)
            self._kitchen_cards[design.id] = card
            self._kitchen_group.addButton(card.radio)
            kitchen_grid.addWidget(card, i // 3, i % 3)
        kitchen_cards_layout.addLayout(kitchen_grid)
        kitchen_layout.addWidget(self._kitchen_cards_wrap)
        body_layout.addWidget(kitchen_box)

        # --- Densité + personnalisation ---
        opts_widget = QWidget()
        opts_form = QFormLayout(opts_widget)
        opts_form.setSpacing(8)

        self.ticket_density = QComboBox()
        self.ticket_density.addItem("Compact", "compact")
        self.ticket_density.addItem("Normal", "normal")
        self.ticket_density.addItem("Aéré", "airy")
        self.ticket_density.setToolTip(
            "Modifie les espaces verticaux sans casser la structure du design."
        )
        _ = DENSITIES

        self.header_align = QComboBox()
        self.header_align.addItem("Centré", "center")
        self.header_align.addItem("À gauche", "left")

        self.opt_show_name = QCheckBox("Nom du commerce")
        self.opt_show_phone = QCheckBox("Téléphone")
        self.opt_show_address = QCheckBox("Adresse")
        self.opt_show_logo = QCheckBox("Logo (si disponible)")
        self.opt_show_logo.setToolTip(
            "Affiche le logo en tête du ticket. "
            "Personnalisé (Commerce → Logo) ou, à défaut, logo du type "
            "(poissonnerie, quincaillerie, pharmacie…). "
            "Bouton « Logo du type » pour appliquer le pictogramme livré."
        )
        self.opt_show_number = QCheckBox("N° ticket")
        self.opt_show_date = QCheckBox("Date")
        self.opt_show_time = QCheckBox("Heure")
        self.opt_show_cashier = QCheckBox("Caissier")
        self.opt_show_subtotal = QCheckBox("Sous-total")
        self.opt_show_discount = QCheckBox("Remise (si présente)")
        self.opt_show_tax = QCheckBox("Taxes (si TVA > 0)")
        self.opt_show_total = QCheckBox("Total")
        self.opt_show_received = QCheckBox("Montant reçu")
        self.opt_show_change = QCheckBox("Monnaie")
        self.opt_hide_zero_change = QCheckBox("Masquer monnaie à 0")
        self.opt_show_payment = QCheckBox("Mode de paiement")
        self.opt_show_footer = QCheckBox("Message de fin")
        self.opt_bold_prices = QCheckBox(
            "Prix des produits en gras (impression thermique)"
        )
        self.opt_bold_total = QCheckBox("Total en gras (impression thermique)")
        self.opt_bold_prices.setToolTip(
            "Appliqué notamment au design Facture tableau (lignes d'articles)."
        )
        self.opt_bold_total.setToolTip(
            "Met en gras la ligne TOTAL et le montant en lettres."
        )

        opts_form.addRow("Densité", self.ticket_density)
        opts_form.addRow("Alignement en-tête", self.header_align)
        opts_form.addRow(section_title("En-tête"))
        for w in (
            self.opt_show_name,
            self.opt_show_phone,
            self.opt_show_address,
            self.opt_show_logo,
        ):
            opts_form.addRow("", w)
        opts_form.addRow(section_title("Informations"))
        for w in (
            self.opt_show_number,
            self.opt_show_date,
            self.opt_show_time,
            self.opt_show_cashier,
        ):
            opts_form.addRow("", w)
        opts_form.addRow(section_title("Totaux"))
        for w in (
            self.opt_show_subtotal,
            self.opt_show_discount,
            self.opt_show_tax,
            self.opt_show_total,
            self.opt_show_received,
            self.opt_show_change,
            self.opt_hide_zero_change,
            self.opt_show_payment,
            self.opt_show_footer,
            self.opt_bold_prices,
            self.opt_bold_total,
        ):
            opts_form.addRow("", w)

        body_layout.addWidget(make_card(opts_widget))

        actions = QHBoxLayout()
        save = QPushButton("Enregistrer les designs")
        save.setObjectName("Primary")
        save.clicked.connect(self._save_designs)
        test_btn = QPushButton("Imprimer un ticket de test")
        test_btn.setToolTip("Imprime un aperçu du design client actuellement sélectionné.")
        test_btn.clicked.connect(self._print_design_test)
        test_kitchen = QPushButton("Tester bon serveur / cuisine")
        test_kitchen.clicked.connect(self._print_kitchen_design_test)
        self._test_kitchen_btn = test_kitchen
        actions.addWidget(save)
        actions.addWidget(test_btn)
        actions.addWidget(test_kitchen)
        actions.addStretch()
        body_layout.addLayout(actions)
        body_layout.addStretch()

        scroll.setWidget(body)
        outer.addWidget(scroll)
        return wrap

    def _on_kitchen_enabled_toggled(self, enabled: bool) -> None:
        self._kitchen_cards_wrap.setEnabled(enabled)
        if hasattr(self, "_test_kitchen_btn"):
            self._test_kitchen_btn.setEnabled(enabled)

    def _on_client_design_selected(self, design_id: str) -> None:
        for did, card in self._client_cards.items():
            card.set_checked(did == design_id)

    def _on_kitchen_design_selected(self, design_id: str) -> None:
        for did, card in self._kitchen_cards.items():
            card.set_checked(did == design_id)

    def _selected_client_design(self) -> str:
        for did, card in self._client_cards.items():
            if card.is_checked():
                return did
        return "classic"

    def _selected_kitchen_design(self) -> str:
        for did, card in self._kitchen_cards.items():
            if card.is_checked():
                return did
        return "serveur"

    def _save_designs(self, silent: bool = False) -> None:
        from app.printers.ticket.options import (
            TicketOptions,
            save_ticket_options,
            set_kitchen_ticket_enabled,
        )

        client_id = self._selected_client_design()
        kitchen_id = self._selected_kitchen_design()
        settings_service.set_setting("ticket_client_design", client_id)
        settings_service.set_setting("ticket_kitchen_design", kitchen_id)
        # Compatibilité ancien paramètre.
        settings_service.set_setting("ticket_layout", client_id)
        set_kitchen_ticket_enabled(self.kitchen_enabled.isChecked())

        opts = TicketOptions(
            density=self.ticket_density.currentData() or "normal",
            show_shop_name=self.opt_show_name.isChecked(),
            show_phone=self.opt_show_phone.isChecked(),
            show_address=self.opt_show_address.isChecked(),
            show_logo=self.opt_show_logo.isChecked(),
            header_align=self.header_align.currentData() or "center",
            show_number=self.opt_show_number.isChecked(),
            show_date=self.opt_show_date.isChecked(),
            show_time=self.opt_show_time.isChecked(),
            show_cashier=self.opt_show_cashier.isChecked(),
            show_subtotal=self.opt_show_subtotal.isChecked(),
            show_discount=self.opt_show_discount.isChecked(),
            show_tax=self.opt_show_tax.isChecked(),
            show_total=self.opt_show_total.isChecked(),
            show_received=self.opt_show_received.isChecked(),
            show_change=self.opt_show_change.isChecked(),
            hide_zero_change=self.opt_hide_zero_change.isChecked(),
            show_payment=self.opt_show_payment.isChecked(),
            show_footer=self.opt_show_footer.isChecked(),
            bold_prices=self.opt_bold_prices.isChecked(),
            bold_total=self.opt_bold_total.isChecked(),
        )
        save_ticket_options(opts)
        self.state.notify_data_changed()
        if not silent:
            info(self, "Designs et options d'affichage enregistrés.")

    def _print_design_test(self) -> None:
        self._save_designs(silent=True)
        from app.printers import thermal_printer

        result = thermal_printer.print_design_test(self._selected_client_design())
        if result.printed:
            info(self, f"Ticket de test envoyé.\n{result.message}", "Test design")
        else:
            warn(
                self,
                f"Impression impossible.\n{result.message}\n\n"
                f"Aperçu enregistré :\n{result.file_path}",
                "Test design",
            )

    def _print_kitchen_design_test(self) -> None:
        from app.printers.ticket.options import is_kitchen_ticket_enabled

        if not is_kitchen_ticket_enabled() and not self.kitchen_enabled.isChecked():
            warn(self, "Le bon serveur / cuisine est désactivé.", "Test cuisine")
            return
        self._save_designs(silent=True)
        from app.printers import thermal_printer

        result = thermal_printer.print_design_test(self._selected_kitchen_design())
        if result.printed:
            info(self, f"Bon de test envoyé.\n{result.message}", "Test cuisine")
        else:
            warn(
                self,
                f"Impression impossible.\n{result.message}\n\n"
                f"Aperçu enregistré :\n{result.file_path}",
                "Test cuisine",
            )

    def _load_designs_ui(self) -> None:
        from app.printers.ticket.options import (
            is_kitchen_ticket_enabled,
            load_ticket_options,
        )
        from app.printers.ticket.registry import (
            resolve_client_design_id,
            resolve_kitchen_design_id,
        )

        client_id = resolve_client_design_id()
        kitchen_id = resolve_kitchen_design_id()
        for did, card in self._client_cards.items():
            card.set_checked(did == client_id)
        for did, card in self._kitchen_cards.items():
            card.set_checked(did == kitchen_id)

        enabled = is_kitchen_ticket_enabled()
        self.kitchen_enabled.blockSignals(True)
        self.kitchen_enabled.setChecked(enabled)
        self.kitchen_enabled.blockSignals(False)
        self._on_kitchen_enabled_toggled(enabled)

        opts = load_ticket_options()
        dens_idx = self.ticket_density.findData(opts.density)
        if dens_idx >= 0:
            self.ticket_density.setCurrentIndex(dens_idx)
        align_idx = self.header_align.findData(opts.header_align)
        if align_idx >= 0:
            self.header_align.setCurrentIndex(align_idx)
        self.opt_show_name.setChecked(opts.show_shop_name)
        self.opt_show_phone.setChecked(opts.show_phone)
        self.opt_show_address.setChecked(opts.show_address)
        self.opt_show_logo.setChecked(opts.show_logo)
        self.opt_show_number.setChecked(opts.show_number)
        self.opt_show_date.setChecked(opts.show_date)
        self.opt_show_time.setChecked(opts.show_time)
        self.opt_show_cashier.setChecked(opts.show_cashier)
        self.opt_show_subtotal.setChecked(opts.show_subtotal)
        self.opt_show_discount.setChecked(opts.show_discount)
        self.opt_show_tax.setChecked(opts.show_tax)
        self.opt_show_total.setChecked(opts.show_total)
        self.opt_show_received.setChecked(opts.show_received)
        self.opt_show_change.setChecked(opts.show_change)
        self.opt_hide_zero_change.setChecked(opts.hide_zero_change)
        self.opt_show_payment.setChecked(opts.show_payment)
        self.opt_show_footer.setChecked(opts.show_footer)
        self.opt_bold_prices.setChecked(opts.bold_prices)
        self.opt_bold_total.setChecked(opts.bold_total)

    def _purge_printer_queue(self) -> None:
        self._save_appearance(silent=True)
        from app.printers import thermal_printer

        result = thermal_printer.purge_printer_queue(self._printer_value())
        if result.printed:
            info(self, result.message, "File d'attente")
        else:
            warn(self, result.message, "File d'attente")

    def _on_printer_profile_changed(self, _index: int = 0) -> None:
        """Aligne le format papier 58/80 mm sur le profil choisi (pas demi-A4)."""
        from app.printers.printer_profile import get_profile

        pid = self.printer_profile.currentData()
        if not pid:
            return
        profile = get_profile(pid)
        current_fmt = self.ticket_format.currentData()
        if current_fmt in ("58mm", "80mm") and current_fmt != profile.paper_width:
            idx = self.ticket_format.findData(profile.paper_width)
            if idx >= 0:
                self.ticket_format.blockSignals(True)
                self.ticket_format.setCurrentIndex(idx)
                self.ticket_format.blockSignals(False)

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

    def _print_encoding_test_page(self) -> None:
        """Test des accents français avec le codepage du profil actif."""
        self._save_appearance(silent=True)
        from app.printers import thermal_printer

        result = thermal_printer.print_encoding_test_page()
        if result.printed:
            info(
                self,
                f"Test accents envoyé.\n{result.message}\n\n"
                "Vérifiez é è à ç œ sur le ticket. "
                "Si caractères chinois ou symboles : changez le profil "
                "(CP850 / CP858 / CP1252) puis réessayez.",
                "Test accents FR",
            )
        else:
            warn(
                self,
                f"Test accents impossible.\n{result.message}\n\n"
                "Vérifiez l'imprimante et le profil ESC/POS.",
                "Test accents FR",
            )

    def _reload_printers(self, select=None) -> None:
        """Détecte les imprimantes installées et remplit la liste déroulante."""
        from app.printers import thermal_printer

        if select is None:
            select = self._printer_value()
        select = (select or "").strip()
        available = thermal_printer.list_printers()
        invalid_cleared = False
        # Liste non vide : prouve l'absence. Liste vide : sonde OpenPrinter/lpstat.
        if select and thermal_printer.is_device_path(select) and not Path(select).exists():
            settings_service.set_setting("printer_name", "")
            select = ""
            invalid_cleared = True
        elif select and not thermal_printer.is_device_path(select):
            matched = thermal_printer.match_printer_in_list(select, available)
            if available and not matched:
                settings_service.set_setting("printer_name", "")
                select = ""
                invalid_cleared = True
            elif not available:
                probed = thermal_printer.probe_printer_exists(select)
                if probed is False:
                    settings_service.set_setting("printer_name", "")
                    select = ""
                    invalid_cleared = True
                elif matched:
                    select = matched
            elif matched:
                select = matched

        self.printer.blockSignals(True)
        self.printer.clear()
        self.printer.addItem(DEFAULT_PRINTER_LABEL, "")
        for name in available:
            self.printer.addItem(name, name)
        if select:
            index = self.printer.findData(select)
            if index >= 0:
                self.printer.setCurrentIndex(index)
            elif thermal_printer.is_device_path(select):
                # Chemin périphérique saisi manuellement encore valide.
                self.printer.setEditText(select)
            else:
                # Nom encore plausible (sonde indéterminée) : garder le texte.
                self.printer.setEditText(select)
        else:
            self.printer.setCurrentIndex(0)
        self.printer.blockSignals(False)
        if invalid_cleared and not getattr(self, "_printer_invalid_warned", False):
            self._printer_invalid_warned = True
            warn(
                self,
                "L'imprimante enregistrée n'existe plus sur ce poste.\n"
                "Sélection : « (Imprimante par défaut) ».\n"
                "Choisissez une imprimante valide dans la liste, puis Appliquer.",
                "Imprimante introuvable",
            )

    def _printer_value(self) -> str:
        """Valeur d'imprimante à enregistrer ('' = imprimante par défaut)."""
        text = self.printer.currentText().strip()
        return "" if text == DEFAULT_PRINTER_LABEL else text

    def _save_appearance(self, silent: bool = False) -> None:
        from app.printers.printer_profile import save_printer_profile_id

        dark = self.theme.currentText() == "Sombre"
        self.state.set_dark(dark)
        settings_service.set_setting("ticket_format", self.ticket_format.currentData())
        pid = self.printer_profile.currentData()
        if pid:
            save_printer_profile_id(pid)
        settings_service.set_setting(
            "pos_catalog_large_text",
            "1" if self.pos_large_text.isChecked() else "0",
        )
        settings_service.set_setting(
            "pos_catalog_text_size", self.pos_text_size.currentData() or "large"
        )
        settings_service.set_setting("printer_name", self._printer_value())
        settings_service.set_setting("ticket_feed_lines", str(self.feed_lines.value()))
        settings_service.set_setting("ticket_cut_mode", self.cut_mode.currentData())
        settings_service.set_setting(
            "auto_print_ticket", "1" if self.auto_print.isChecked() else "0"
        )
        settings_service.save_shop_info(ticket_footer=self.footer.text().strip())
        self.state.notify_data_changed()
        if not silent:
            info(self, "Préférences appliquées.")

    # --- Onglet contrôles caisse (plafonds caissier) -----------------------
    def _build_controls_tab(self) -> QWidget:
        from app.services import cash_controls

        wrap = QWidget()
        outer = QVBoxLayout(wrap)
        hint = QLabel(
            "Plafonds appliqués uniquement au rôle <b>Caissier</b> "
            "(Administrateur et Gestionnaire : sans limite)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b;")
        outer.addWidget(hint)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setSpacing(10)
        self.max_discount_pct = QDoubleSpinBox()
        self.max_discount_pct.setRange(0, 100)
        self.max_discount_pct.setDecimals(0)
        self.max_discount_pct.setSuffix(" %")
        self.max_discount_pct.setValue(cash_controls.get_max_discount_percent())
        self.max_credit_amount = QDoubleSpinBox()
        self.max_credit_amount.setRange(0, 1_000_000_000)
        self.max_credit_amount.setDecimals(0)
        self.max_credit_amount.setValue(cash_controls.get_max_credit_amount())
        self.max_free_amount = QDoubleSpinBox()
        self.max_free_amount.setRange(0, 1_000_000_000)
        self.max_free_amount.setDecimals(0)
        self.max_free_amount.setValue(cash_controls.get_max_free_amount())
        self.variance_threshold = QDoubleSpinBox()
        self.variance_threshold.setRange(0, 1_000_000_000)
        self.variance_threshold.setDecimals(0)
        self.variance_threshold.setValue(cash_controls.get_variance_note_threshold())
        form.addRow("Remise max caissier", self.max_discount_pct)
        form.addRow("Dette max caissier (par vente)", self.max_credit_amount)
        form.addRow("Montant libre max (par ligne)", self.max_free_amount)
        form.addRow("Écart caisse → note obligatoire", self.variance_threshold)
        outer.addWidget(make_card(form_widget))

        save = QPushButton("Enregistrer les plafonds")
        save.setObjectName("Primary")
        save.clicked.connect(self._save_controls)
        outer.addWidget(save)
        outer.addStretch()
        return wrap

    def _save_controls(self) -> None:
        from app.services import cash_controls

        cash_controls.set_limits(
            self.max_discount_pct.value(),
            self.max_credit_amount.value(),
            free_amount=self.max_free_amount.value(),
            variance_threshold=self.variance_threshold.value(),
        )
        audit_service.log_action(
            "Plafonds caisse",
            "Setting",
            f"remise={self.max_discount_pct.value()}% "
            f"crédit={self.max_credit_amount.value()} "
            f"libre={self.max_free_amount.value()} "
            f"écart_note={self.variance_threshold.value()}",
            self.state.user_id,
            getattr(self.state.current_user, "username", ""),
        )
        info(self, "Plafonds caissier enregistrés.")

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
        self.auto_interval = QSpinBox()
        self.auto_interval.setRange(1, 24 * 365)
        self.auto_interval.setSuffix(" heures")
        self.retention = QSpinBox()
        self.retention.setRange(1, 200)
        self.retention.setValue(backup_service.DEFAULT_RETENTION)
        self.retention.setSuffix(" sauvegardes conservées")
        auto_form.addRow(self.auto_enabled)
        auto_form.addRow("Fréquence", self.auto_frequency)
        auto_form.addRow("Intervalle", self.auto_interval)
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
        if not self.state.can(perms.MANAGE_SETTINGS):
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
            "L'application va se fermer. Veuillez la relancer pour utiliser "
            "les données restaurées.",
            "Restauration terminée",
        )
        # Fermeture forcée : évite tout état incohérent en mémoire après le
        # remplacement de la base de données.
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.quit()
        else:
            QApplication.quit()

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
            backup_service.SETTING_AUTO_INTERVAL_HOURS,
            str(self.auto_interval.value()),
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
        self.auto_interval.setValue(backup_service.get_interval_hours())
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
        # 0 Commerce, 1 Apparence, 2 Designs, 3 Contrôles, 4 Sauvegarde, 5 Audit
        if index == 2:
            self._load_designs_ui()
        elif index == 4:
            self._load_auto_options()
            self._reload_backups()
        elif index == 5:
            self._reload_audit()

    # --- Rafraîchissement --------------------------------------------------
    def refresh(self) -> None:
        shop = settings_service.get_shop_info()
        self.name.setText(shop.name)
        self.address.setText(shop.address)
        self.phone.setText(shop.phone)
        self.email.setText(shop.email)
        self.fax.setText(settings_service.get_setting("shop_fax", ""))
        self.currency.setCurrentText(shop.currency)
        idx = self.shop_type.findText(shop.shop_type)
        if idx >= 0:
            self.shop_type.setCurrentIndex(idx)
        self.vat.setValue(float(shop.vat_rate or 0))
        self.logo_label.setText(shop.logo_path)
        self.footer.setText(shop.ticket_footer)
        self.theme.setCurrentText("Sombre" if self.state.dark else "Clair")
        fmt = settings_service.get_setting("ticket_format", "80mm")
        fmt_index = self.ticket_format.findData(fmt)
        if fmt_index < 0:
            # Anciennes valeurs stockées comme texte simple.
            fmt_index = self.ticket_format.findText(fmt)
        if fmt_index >= 0:
            self.ticket_format.setCurrentIndex(fmt_index)
        from app.printers.printer_profile import (
            DEFAULT_PROFILE_ID_58,
            DEFAULT_PROFILE_ID_80,
            SETTING_PRINTER_PROFILE,
        )

        pid = settings_service.get_setting(SETTING_PRINTER_PROFILE, "")
        if not pid:
            pid = (
                DEFAULT_PROFILE_ID_58
                if fmt == "58mm"
                else DEFAULT_PROFILE_ID_80
            )
        p_index = self.printer_profile.findData(pid)
        if p_index >= 0:
            self.printer_profile.blockSignals(True)
            self.printer_profile.setCurrentIndex(p_index)
            self.printer_profile.blockSignals(False)
        large = settings_service.get_setting("pos_catalog_large_text", "0") == "1"
        self.pos_large_text.setChecked(large)
        self.pos_text_size.setEnabled(large)
        size_index = self.pos_text_size.findData(
            settings_service.get_setting("pos_catalog_text_size", "large")
        )
        if size_index >= 0:
            self.pos_text_size.setCurrentIndex(size_index)
        self._reload_printers(select=settings_service.get_setting("printer_name", ""))
        try:
            self.feed_lines.setValue(int(settings_service.get_setting("ticket_feed_lines", "5")))
        except (TypeError, ValueError):
            self.feed_lines.setValue(5)
        cut_index = self.cut_mode.findData(
            settings_service.get_setting("ticket_cut_mode", "full")
        )
        if cut_index >= 0:
            self.cut_mode.setCurrentIndex(cut_index)
        self.auto_print.setChecked(
            settings_service.get_setting("auto_print_ticket", "0") == "1"
        )
        self._load_designs_ui()
        self._load_auto_options()
        self._reload_backups()
