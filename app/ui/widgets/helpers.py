"""Petites fabriques d'éléments d'interface pour réduire la duplication."""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QLabel, QMessageBox, QVBoxLayout, QWidget

from app.i18n import t


def activate_and_center(widget: QWidget) -> None:
    """Place une fenêtre au centre de l'écran et lui donne le focus.

    Utile pour les boîtes de dialogue affichées séquentiellement (assistant puis
    connexion) : certains gestionnaires de fenêtres légers (VNC) n'activent pas
    automatiquement la nouvelle fenêtre, ce qui la rendait non réactive.
    """
    widget.raise_()
    widget.activateWindow()
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        geometry = widget.frameGeometry()
        geometry.moveCenter(screen.availableGeometry().center())
        widget.move(geometry.topLeft())


def make_card(child: QWidget | None = None) -> QFrame:
    """Retourne un cadre stylé en « carte » contenant éventuellement un widget."""
    card = QFrame()
    card.setObjectName("Card")
    if child is not None:
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(child)
    return card


def page_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("PageTitle")
    return label


def section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionTitle")
    return label


def info(parent, message: str, title: str | None = None) -> None:
    QMessageBox.information(parent, title or t("common.info"), message)


def warn(parent, message: str, title: str | None = None) -> None:
    QMessageBox.warning(parent, title or t("common.warning"), message)


def error(parent, message: str, title: str | None = None) -> None:
    QMessageBox.critical(parent, title or t("common.error"), message)


def confirm(parent, message: str, title: str | None = None) -> bool:
    reply = QMessageBox.question(
        parent,
        title or t("common.confirm"),
        message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return reply == QMessageBox.StandardButton.Yes
