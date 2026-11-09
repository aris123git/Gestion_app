"""Navigation au clavier partout : Tab / Entrée / flèches / raccourcis, avec focus bien visible.

Installé une seule fois sur l'application (filtre d'événements) :
- Entrée sur un bouton = clic (comme Espace) ;
- Entrée dans un formulaire (fenêtre de saisie) = champ suivant ; sur le dernier champ, elle valide comme avant ;
- Entrée sur une ligne de tableau = ouvrir / modifier (équivaut au double-clic) ;
- ↑ ↓ dans le menu latéral = changer de rubrique ;
- Ctrl+1…9 (dans MainWindow) = aller à la rubrique n.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QLineEdit, QPlainTextEdit, QPushButton,
    QTextEdit, QWidget,
)

_ENTER = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


def _owner_dialog(widget: QWidget):
    w = widget
    while w is not None:
        if isinstance(w, QDialog):
            return w
        w = w.parentWidget()
    return None


def _is_last_input(widget: QWidget) -> bool:
    """Vrai si, après ce champ, le prochain élément focalisable est un bouton (donc Entrée = valider)."""
    nxt = widget.nextInFocusChain()
    guard = 0
    while nxt is not None and nxt is not widget and guard < 200:
        guard += 1
        if nxt.isVisible() and nxt.isEnabled() and nxt.focusPolicy() != Qt.FocusPolicy.NoFocus:
            return isinstance(nxt, (QAbstractButton, QDialogButtonBox))
        nxt = nxt.nextInFocusChain()
    return True


def _field_of(widget: QWidget):
    """Le champ « logique » : le QLineEdit interne d'un spinbox / combo éditable compte pour son parent."""
    if isinstance(widget, QLineEdit):
        parent = widget.parentWidget()
        if parent is not None and not isinstance(parent, QDialog) and parent.focusPolicy() != Qt.FocusPolicy.NoFocus and parent.inherits("QAbstractSpinBox"):
            return parent
        if isinstance(parent, QComboBox):
            return parent
    return widget


class KeyboardNavigation(QObject):
    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() != QEvent.Type.KeyPress or not isinstance(obj, QWidget):
            return False
        key = event.key()
        mods = event.modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            return False
        # Entrée sur un bouton
        if key in _ENTER and isinstance(obj, QPushButton) and obj.isEnabled():
            obj.click()
            return True
        # Entrée sur un tableau / une liste : ouvrir la ligne
        if key in _ENTER and isinstance(obj, QAbstractItemView) and obj.state() != QAbstractItemView.State.EditingState:
            index = obj.currentIndex()
            if index.isValid():
                obj.doubleClicked.emit(index)
                return True
            return False
        # Entrée dans un formulaire : champ suivant
        if key in _ENTER and isinstance(obj, (QLineEdit, QComboBox)) and not isinstance(obj, (QPlainTextEdit, QTextEdit)):
            field = _field_of(obj)
            dialog = _owner_dialog(field)
            if dialog is None or isinstance(field, QComboBox) and field.view().isVisible():
                return False
            if _is_last_input(field):
                return False
            dialog.focusNextChild()
            return True
        # Menu latéral : flèches haut / bas
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and isinstance(obj, QPushButton) and obj.objectName() == "NavButton":
            nxt = obj.nextInFocusChain() if key == Qt.Key.Key_Down else obj.previousInFocusChain()
            if isinstance(nxt, QPushButton) and nxt.objectName() == "NavButton" and nxt.isEnabled() and nxt.isVisible():
                nxt.setFocus(Qt.FocusReason.TabFocusReason)
                return True
        return False


_instance: KeyboardNavigation | None = None


def install(app: QApplication | None = None) -> None:
    global _instance
    app = app or QApplication.instance()
    if app is None or _instance is not None:
        return
    _instance = KeyboardNavigation(app)
    app.installEventFilter(_instance)
