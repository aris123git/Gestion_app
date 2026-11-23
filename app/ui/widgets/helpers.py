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


def plainify(root: QWidget) -> None:
    """Rend transparents les simples conteneurs (QWidget nus) d'une page : plus de bandes grises dans les cartes blanches."""
    for w in root.findChildren(QWidget):
        if type(w) is QWidget and not w.objectName():
            w.setObjectName("Plain")
            w.style().unpolish(w)
            w.style().polish(w)


def make_card(child: QWidget | None = None) -> QFrame:
    """Retourne un cadre stylé en « carte » contenant éventuellement un widget."""
    card = QFrame()
    card.setObjectName("Card")
    if child is not None:
        if type(child) is QWidget:
            child.setObjectName('Plain')  # pas de bande grise dans la carte blanche
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(child)
    return card


def dialog_header_banner(caption: str, detail: str = "", *, background: str | None = None) -> QFrame:
    """Bandeau d'en-tête coloré utilisé en haut des fenêtres pop-up (titre + sous-titre),
    dans le même esprit que le Tableau de bord et les Paramètres."""
    banner = QFrame()
    banner.setObjectName("DialogHeaderBanner")
    if background:
        banner.setStyleSheet(f"background-color: {background};")
    layout = QVBoxLayout(banner)
    layout.setContentsMargins(20, 14, 20, 16)
    layout.setSpacing(2)
    title = QLabel(caption)
    title.setStyleSheet("font-size: 18px; font-weight: 800;")
    layout.addWidget(title)
    if detail:
        sub = QLabel(detail)
        sub.setStyleSheet("font-size: 12px;")
        sub.setWordWrap(True)
        layout.addWidget(sub)
    return banner


def dialog_summary_banner(label: QLabel) -> QFrame:
    """Bandeau sombre de résumé (ex. encaissé / monnaie / écart) placé en bas d'un dialogue."""
    banner = QFrame()
    banner.setObjectName("DialogSummaryBanner")
    layout = QVBoxLayout(banner)
    layout.setContentsMargins(14, 12, 14, 12)
    label.setWordWrap(True)
    layout.addWidget(label)
    return banner


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
