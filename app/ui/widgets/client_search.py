"""Champ de recherche client avec suggestions progressives (nom / téléphone)."""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QStringListModel, Qt, QTimer, Signal
from PySide6.QtWidgets import QCompleter, QHBoxLayout, QLabel, QLineEdit, QWidget

from app.controllers.client_controller import ClientController


class ClientSearchField(QWidget):
    """Saisie libre : affiche les clients dont le nom ou le téléphone correspond.

    Signal ``client_selected(client_id|None)`` émis à la sélection / validation.
    """

    client_selected = Signal(object)

    def __init__(self, parent=None, placeholder: str = "Nom ou téléphone du client…"):
        super().__init__(parent)
        self._clients_by_label: Dict[str, int] = {}
        self._selected_id: Optional[int] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.input = QLineEdit()
        self.input.setPlaceholderText(placeholder)
        self.input.setClearButtonEnabled(True)
        layout.addWidget(self.input, 1)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(self.status)

        self._model = QStringListModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setMaxVisibleItems(12)
        self.input.setCompleter(self._completer)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._refresh_suggestions)

        self.input.textEdited.connect(self._on_text_edited)
        self.input.returnPressed.connect(self._accept_current)
        self._completer.activated[str].connect(self._on_completer_activated)

    @property
    def client_id(self) -> Optional[int]:
        return self._selected_id

    def set_client(self, client_id: Optional[int], *, emit: bool = False) -> None:
        """Affiche un client déjà choisi (sans forcément émettre le signal)."""
        self._selected_id = client_id
        if client_id is None:
            self.input.blockSignals(True)
            self.input.clear()
            self.input.blockSignals(False)
            self.status.setText("")
            if emit:
                self.client_selected.emit(None)
            return
        client = ClientController.get(client_id)
        if not client:
            self._selected_id = None
            self.status.setText("")
            return
        label = self._label_for(client)
        self._clients_by_label[label] = client.id
        self.input.blockSignals(True)
        self.input.setText(label)
        self.input.blockSignals(False)
        phone = (client.phone or client.phone2 or "").strip()
        self.status.setText(f"✓ {client.name}" + (f" — {phone}" if phone else ""))
        self.status.setStyleSheet("color: #16a34a; font-size: 12px;")
        if emit:
            self.client_selected.emit(client.id)

    def text(self) -> str:
        return self.input.text().strip()

    def clear(self) -> None:
        self.set_client(None)

    @staticmethod
    def _label_for(client) -> str:
        phone = (client.phone or client.phone2 or "").strip()
        if phone:
            return f"{client.name} — {phone}"
        return client.name

    def _on_text_edited(self, _text: str) -> None:
        # Toute édition manuelle invalide la sélection jusqu'à confirmation.
        self._selected_id = None
        self.status.setText("Suggestions…")
        self.status.setStyleSheet("color: #64748b; font-size: 12px;")
        self._timer.start()

    def _refresh_suggestions(self) -> None:
        query = self.input.text().strip()
        if len(query) < 1:
            self._model.setStringList([])
            self._clients_by_label.clear()
            self.status.setText("")
            self.client_selected.emit(None)
            return
        clients: List = ClientController.list(search=query)[:30]
        labels: List[str] = []
        mapping: Dict[str, int] = {}
        for client in clients:
            label = self._label_for(client)
            # Évite les doublons de libellé.
            if label in mapping:
                label = f"{label} #{client.id}"
            labels.append(label)
            mapping[label] = client.id
        self._clients_by_label = mapping
        self._model.setStringList(labels)
        if labels:
            self._completer.complete()
            self.status.setText(f"{len(labels)} correspondance(s)")
            self.status.setStyleSheet("color: #64748b; font-size: 12px;")
        else:
            self.status.setText("Aucun client — Entrée pour créer via téléphone")
            self.status.setStyleSheet("color: #b45309; font-size: 12px;")

    def _on_completer_activated(self, label: str) -> None:
        client_id = self._clients_by_label.get(label)
        if client_id is None:
            return
        self.set_client(client_id, emit=True)

    def _accept_current(self) -> None:
        text = self.input.text().strip()
        if not text:
            self.set_client(None, emit=True)
            return
        if text in self._clients_by_label:
            self.set_client(self._clients_by_label[text], emit=True)
            return
        # Première suggestion si unique correspondance partielle.
        if len(self._clients_by_label) == 1:
            only_id = next(iter(self._clients_by_label.values()))
            self.set_client(only_id, emit=True)
            return
        # Sinon laisse le parent gérer (création par téléphone, etc.).
        self.client_selected.emit(None)
