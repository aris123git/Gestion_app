"""Messages groupés aux clients : WhatsApp (un par un, validé par la personne) et e-mail (envoi séquentiel)."""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QDate, QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
    QProgressBar, QPushButton, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.i18n import t
from app.services import audit_service, messaging_service as ms, settings_service
from app.ui.widgets.dialog_fit import fit_dialog_to_screen
from app.ui.widgets.helpers import confirm, info, warn

DEFAULT_TEXT = "Bonjour {prenom}, merci pour votre confiance. [Votre message ici] — {entreprise}"


class EmailConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Compte e-mail d'envoi"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=460, min_height=360, preferred_width=540, preferred_height=430)
        form = QFormLayout(self)
        hint = QLabel(t("Ex. Gmail : serveur smtp.gmail.com, port 465, sécurité SSL, et un « mot de passe d'application » (pas votre mot de passe habituel)."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b;")
        form.addRow(hint)
        self.host = QLineEdit(ms.cfg("messaging_smtp_host"))
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(ms.cfg_int("messaging_smtp_port") or 465)
        self.security = QComboBox()
        self.security.addItem("SSL (465)", "ssl")
        self.security.addItem("STARTTLS (587)", "starttls")
        self.security.setCurrentIndex(max(0, self.security.findData(ms.cfg("messaging_smtp_security"))))
        self.user = QLineEdit(ms.cfg("messaging_smtp_user"))
        self.password = QLineEdit(ms.cfg("messaging_smtp_password"))
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.from_name = QLineEdit(ms.cfg("messaging_from_name"))
        for label, w in ((t("Serveur SMTP"), self.host), (t("Port"), self.port), (t("Sécurité"), self.security), (t("Adresse e-mail"), self.user),
                         (t("Mot de passe"), self.password), (t("Nom affiché"), self.from_name)):
            form.addRow(label, w)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _save(self) -> None:
        try:
            ms.save_email_config(host=self.host.text(), port=self.port.value(), security=self.security.currentData(), user=self.user.text(),
                                 password=self.password.text(), from_name=self.from_name.text())
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.accept()


class _EmailWorker(QThread):
    progressed = Signal(int, int, str)

    def __init__(self, recipients, subject, template, campaign, shop, currency, footer, delay):
        super().__init__()
        self._args = (recipients, subject, template, campaign, shop, currency, footer, delay)
        self._stop = False
        self.result: dict = {}
        self.error = ""

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        recipients, subject, template, campaign, shop, currency, footer, delay = self._args
        try:
            self.result = ms.send_email_campaign(
                recipients, subject, template, campaign=campaign, shop_name=shop, currency=currency, footer=footer, delay=delay,
                progress=lambda i, n, r, status: self.progressed.emit(i, n, f"{r.name} <{r.email}> — {status}"), should_stop=lambda: self._stop)
        except Exception as exc:
            self.error = str(exc)


class BulkMessageDialog(QDialog):
    def __init__(self, parent=None, user_id=None, username=""):
        super().__init__(parent)
        self.user_id, self.username = user_id, username
        self.setWindowTitle(t("Message groupé aux clients"))
        self.setModal(True)
        fit_dialog_to_screen(self, min_width=720, min_height=620, preferred_width=860, preferred_height=760)
        self.recipients: list = []
        self.queue: list = []
        self.position = 0
        self.worker = None
        self.shop = settings_service.get_shop_info()
        self.currency = self.shop.currency or "FCFA"
        root = QVBoxLayout(self)
        self.stack = QStackedWidget()
        root.addWidget(self.stack)
        self.stack.addWidget(self._build_setup())
        self.stack.addWidget(self._build_whatsapp())
        self.stack.addWidget(self._build_email())

    # -- configuration -------------------------------------------------------------------------
    def _build_setup(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        note = QLabel(t("Les messages partent un par un, uniquement vers vos clients enregistrés, jamais vers ceux marqués « ne plus contacter », "
                        "avec un plafond par jour. WhatsApp s'ouvre pré-rempli : c'est vous qui appuyez sur Envoyer."))
        note.setWordWrap(True)
        note.setStyleSheet("color: #64748b;")
        lay.addWidget(note)
        form = QFormLayout()
        self.channel = QComboBox()
        self.channel.addItem("WhatsApp", ms.WHATSAPP)
        self.channel.addItem(t("E-mail"), ms.EMAIL)
        self.segment = QComboBox()
        for key, label in ms.SEGMENT_LABELS.items():
            self.segment.addItem(t(label), key)
        today = QDate.currentDate()
        self.d_from = QDateEdit(today.addDays(-7))
        self.d_to = QDateEdit(today)
        for d in (self.d_from, self.d_to):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd/MM/yyyy")
        self.dates = QWidget()
        h = QHBoxLayout(self.dates)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel(t("Du")))
        h.addWidget(self.d_from)
        h.addWidget(QLabel(t("au (inclus)")))
        h.addWidget(self.d_to)
        h.addStretch()
        self.days = QSpinBox()
        self.days.setRange(1, 3650)
        self.days.setValue(90)
        self.days.setSuffix(" " + t("jours"))
        self.subject = QLineEdit()
        self.subject.setPlaceholderText(t("Objet de l'e-mail"))
        self.text = QPlainTextEdit(DEFAULT_TEXT)
        self.text.setMinimumHeight(110)
        self.footer = QCheckBox(t("Ajouter « répondez STOP pour ne plus recevoir nos messages » (recommandé)"))
        self.footer.setChecked(True)
        form.addRow(t("Canal"), self.channel)
        form.addRow(t("Destinataires"), self.segment)
        form.addRow(t("Période d'achat"), self.dates)
        form.addRow(t("Sans achat depuis"), self.days)
        form.addRow(t("Objet"), self.subject)
        form.addRow(t("Message"), self.text)
        hint = QLabel(t("Variables : {nom}  {prenom}  {dette}  {entreprise}"))
        hint.setStyleSheet("color: #64748b;")
        form.addRow("", hint)
        form.addRow("", self.footer)
        lay.addLayout(form)
        row = QHBoxLayout()
        show = QPushButton(t("Afficher les destinataires"))
        show.clicked.connect(self._load_recipients)
        self.btn_cfg = QPushButton(t("Compte e-mail…"))
        self.btn_cfg.clicked.connect(lambda: EmailConfigDialog(self).exec())
        row.addWidget(show)
        row.addWidget(self.btn_cfg)
        row.addStretch()
        lay.addLayout(row)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([t("Client"), t("Téléphone"), t("E-mail"), t("Dette")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)
        self.count = QLabel()
        self.count.setWordWrap(True)
        lay.addWidget(self.count)
        row = QHBoxLayout()
        close = QPushButton(t("Fermer"))
        close.clicked.connect(self.reject)
        self.start = QPushButton(t("Démarrer l'envoi"))
        self.start.setObjectName("Primary")
        self.start.clicked.connect(self._start)
        row.addWidget(close)
        row.addStretch()
        row.addWidget(self.start)
        lay.addLayout(row)
        self.channel.currentIndexChanged.connect(self._sync_fields)
        self.segment.currentIndexChanged.connect(self._sync_fields)
        self._sync_fields()
        return w

    def _sync_fields(self, *_a) -> None:
        seg, email = self.segment.currentData(), self.channel.currentData() == ms.EMAIL
        self.dates.setVisible(seg == ms.SEG_BOUGHT)
        self.days.setVisible(seg == ms.SEG_INACTIVE)
        self.subject.setVisible(email)
        self.btn_cfg.setVisible(email)
        self.table.setRowCount(0)
        self.recipients = []
        self.count.setText("")

    def _load_recipients(self) -> None:
        a, b = self.d_from.date(), self.d_to.date()
        try:
            rows = ms.find_recipients(self.segment.currentData(), self.channel.currentData(),
                                      start=datetime(a.year(), a.month(), a.day()), end=datetime(b.year(), b.month(), b.day()) + timedelta(days=1),
                                      days=self.days.value())
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.recipients = rows
        self.table.setRowCount(len(rows))
        for r, rc in enumerate(rows):
            name = QTableWidgetItem(rc.name)
            name.setFlags(name.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            name.setCheckState(Qt.CheckState.Checked)
            name.setData(Qt.ItemDataRole.UserRole, r)
            self.table.setItem(r, 0, name)
            for c, v in enumerate((rc.phone, rc.email, f"{rc.debt:,.0f}".replace(",", " ") if rc.debt else ""), 1):
                self.table.setItem(r, c, QTableWidgetItem(v))
        left = ms.remaining_today(self.channel.currentData())
        msg = f"<b>{len(rows)}</b> {t('destinataire(s)')} · {t('plafond restant aujourd’hui')} : <b>{left}</b>"
        if len(rows) > left:
            msg += f"<br/><span style='color:#b45309'>{t('Seuls les')} {left} {t('premiers seront traités aujourd’hui ; reprenez demain pour les autres.')}</span>"
        self.count.setText(msg)

    def _selected(self) -> list:
        out = []
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).checkState() == Qt.CheckState.Checked:
                out.append(self.recipients[self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)])
        return out

    def _start(self) -> None:
        if not self.recipients:
            self._load_recipients()
        chosen = self._selected()
        channel = self.channel.currentData()
        if not chosen:
            warn(self, t("Aucun destinataire sélectionné."))
            return
        if not self.text.toPlainText().strip():
            warn(self, t("Le message est vide."))
            return
        left = ms.remaining_today(channel)
        if left <= 0:
            warn(self, t("Plafond du jour atteint pour ce canal. Reprenez demain (cela protège votre numéro et votre adresse)."))
            return
        chosen = chosen[:left]
        self.campaign = f"{datetime.now():%Y-%m-%d %H:%M} {self.segment.currentData()}"
        audit_service.log_action("Message groupé", "Clients", f"{channel} · {len(chosen)} destinataire(s)", self.user_id, self.username)
        if channel == ms.WHATSAPP:
            self.queue, self.position = chosen, 0
            self.stack.setCurrentIndex(1)
            self._show_current()
        else:
            if not ms.email_configured():
                warn(self, t("Configurez d'abord le compte e-mail d'envoi (bouton « Compte e-mail… »)."))
                return
            if not confirm(self, f"{t('Envoyer')} {len(chosen)} {t('e-mail(s), un par un, avec un délai entre chaque ?')}"):
                return
            self._run_email(chosen)

    # -- WhatsApp : file un par un ------------------------------------------------------------
    def _build_whatsapp(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.wa_title = QLabel()
        self.wa_title.setTextFormat(Qt.TextFormat.RichText)
        self.wa_progress = QProgressBar()
        self.wa_preview = QPlainTextEdit()
        self.wa_preview.setReadOnly(True)
        hint = QLabel(t("1) Ouvrez WhatsApp (le message est pré-rempli)  2) Appuyez sur Envoyer dans WhatsApp  3) Revenez ici et cliquez « Envoyé »."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b;")
        lay.addWidget(self.wa_title)
        lay.addWidget(self.wa_progress)
        lay.addWidget(self.wa_preview, 1)
        lay.addWidget(hint)
        row = QHBoxLayout()
        self.wa_open = QPushButton(t("Ouvrir WhatsApp"))
        self.wa_open.setObjectName("Primary")
        self.wa_sent = QPushButton(t("Envoyé ✓ — suivant"))
        self.wa_sent.setObjectName("Success")
        self.wa_skip = QPushButton(t("Passer"))
        self.wa_optout = QPushButton(t("Ne plus contacter"))
        self.wa_optout.setObjectName("Danger")
        self.wa_stop = QPushButton(t("Arrêter"))
        self.wa_open.clicked.connect(self._wa_open)
        self.wa_sent.clicked.connect(lambda: self._wa_next(ms.SENT))
        self.wa_skip.clicked.connect(lambda: self._wa_next(ms.SKIPPED))
        self.wa_optout.clicked.connect(self._wa_optout)
        self.wa_stop.clicked.connect(self._wa_finish)
        for b in (self.wa_open, self.wa_sent, self.wa_skip, self.wa_optout, self.wa_stop):
            row.addWidget(b)
        lay.addLayout(row)
        return w

    def _wa_message(self, r) -> str:
        return ms.render(self.text.toPlainText(), r, self.shop.name or "", self.currency, self.footer.isChecked())

    def _show_current(self) -> None:
        if self.position >= len(self.queue):
            self._wa_finish()
            return
        r = self.queue[self.position]
        self.wa_title.setText(f"<b>{self.position + 1} / {len(self.queue)}</b> — {r.name} ({r.phone})")
        self.wa_progress.setMaximum(len(self.queue))
        self.wa_progress.setValue(self.position)
        self.wa_preview.setPlainText(self._wa_message(r))
        self.wa_sent.setEnabled(False)

    def _wa_open(self) -> None:
        r = self.queue[self.position]
        try:
            QDesktopServices.openUrl(QUrl(ms.whatsapp_link(r.phone, self._wa_message(r))))
        except ValueError as exc:
            warn(self, str(exc))
            return
        self.wa_sent.setEnabled(True)

    def _wa_next(self, status: str) -> None:
        r = self.queue[self.position]
        ms.log(r.id, ms.WHATSAPP, status, self.campaign)
        self.position += 1
        if ms.remaining_today(ms.WHATSAPP) <= 0 and self.position < len(self.queue):
            info(self, t("Plafond du jour atteint : arrêt pour protéger votre numéro WhatsApp. Reprenez demain."))
            self._wa_finish()
            return
        self._show_current()

    def _wa_optout(self) -> None:
        r = self.queue[self.position]
        if confirm(self, f"{t('Ne plus jamais contacter')} {r.name} ?"):
            ms.opt_out(r.id)
            ms.log(r.id, ms.WHATSAPP, ms.SKIPPED, self.campaign, "désinscrit")
            self.position += 1
            self._show_current()

    def _wa_finish(self) -> None:
        done = self.position
        info(self, f"{done} {t('conversation(s) traitée(s).')}")
        self.accept()

    # -- e-mail : envoi séquentiel en arrière-plan ---------------------------------------------------
    def _build_email(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.em_bar = QProgressBar()
        self.em_log = QPlainTextEdit()
        self.em_log.setReadOnly(True)
        self.em_stop = QPushButton(t("Arrêter"))
        self.em_stop.clicked.connect(self._email_stop)
        lay.addWidget(self.em_bar)
        lay.addWidget(self.em_log, 1)
        lay.addWidget(self.em_stop)
        return w

    def _run_email(self, chosen: list) -> None:
        self.stack.setCurrentIndex(2)
        self.em_bar.setMaximum(len(chosen))
        self.em_bar.setValue(0)
        self.em_log.clear()
        self.em_stop.setText(t("Arrêter"))
        self.worker = _EmailWorker(chosen, self.subject.text(), self.text.toPlainText(), self.campaign, self.shop.name or "", self.currency,
                                   self.footer.isChecked(), None)
        self.worker.progressed.connect(self._email_progress)
        self.worker.finished.connect(self._email_done)
        self.worker.start()

    def _email_progress(self, i: int, n: int, line: str) -> None:
        self.em_bar.setValue(i)
        self.em_log.appendPlainText(f"{i}/{n}  {line}")

    def _email_stop(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.em_stop.setEnabled(False)
        else:
            self.accept()

    def _email_done(self) -> None:
        w = self.worker
        res = w.result if w else {}
        if w and w.error:
            self.em_log.appendPlainText(f"{t('Erreur')} : {w.error}")
        else:
            tail = f"{t('Terminé')} : {res.get('sent', 0)} {t('envoyé(s)')}, {res.get('failed', 0)} {t('échec(s)')}"
            if res.get("capped"):
                tail += f" — {t('plafond du jour atteint, reprenez demain')}"
            if res.get("stopped"):
                tail += f" — {t('arrêté')}"
            self.em_log.appendPlainText(tail)
        self.em_stop.setEnabled(True)
        self.em_stop.setText(t("Fermer"))

    def reject(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(15000)
        super().reject()
