"""Application automatique et centralisée du moteur responsive à toute page.

Un seul appel — fait une fois dans ``MainWindow._build_pages()`` — suffit :
chaque page bénéficie d'un comportement adaptatif minimal (marges qui suivent
la densité, tables qui ne débordent jamais de la fenêtre) sans avoir à écrire
le moindre code responsive dans son propre fichier.

Les pages qui gèrent déjà leur propre ``_on_layout_changed`` avec un
``TableColumnController`` (ex. ``pos_page``, ``products_page``) ne sont pas
perturbées : ce module ajoute un filet de sécurité générique par-dessus, il
ne remplace rien et peut être appelé sans risque sur n'importe quelle page.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QScrollArea, QTableWidget, QWidget

from app.ui.responsive.viewport import LayoutProfile


def apply_generic_responsiveness(page: QWidget, state) -> None:
    """Branche ``page`` sur ``state.layout_changed`` avec un comportement générique.

    - Ajuste les marges du layout principal de la page selon la densité.
    - Empêche toute ``QTableWidget`` de déborder de la fenêtre (barre de
      défilement horizontale + dernière colonne étirée) au lieu de couper
      le contenu ou de forcer la fenêtre à s'agrandir.
    - Réduit légèrement la police des tables en mode compact (petit écran).
    - Rend chaque ``QScrollArea`` redimensionnable avec son contenu.
    """

    def _on_layout_changed(profile: LayoutProfile) -> None:
        layout = page.layout()
        if layout is not None:
            if profile.density == "compact":
                margins = 12
            elif profile.density == "cozy":
                margins = 16
            else:
                margins = 24
            layout.setContentsMargins(margins, margins, margins, margins)

        for table in page.findChildren(QTableWidget):
            header = table.horizontalHeader()
            if header is not None:
                header.setStretchLastSection(True)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            table.setWordWrap(True)
            if profile.density == "compact":
                font = QFont(table.font())
                font.setPointSize(max(9, font.pointSize() - 1))
                table.setFont(font)
                vheader = table.verticalHeader()
                if vheader is not None:
                    vheader.setDefaultSectionSize(28)

        for area in page.findChildren(QScrollArea):
            area.setWidgetResizable(True)

    state.layout_changed.connect(_on_layout_changed)
    if state.layout is not None:
        _on_layout_changed(state.layout)
    # Référence conservée sur la page pour éviter que le handler (et donc la
    # connexion au signal) ne soit collecté par le ramasse-miettes Python.
    page._generic_responsive_handler = _on_layout_changed
