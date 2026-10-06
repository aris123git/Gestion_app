"""Moteur responsive centralisé (viewport, layout, tables prioritaires)."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QScrollArea, QTableWidget, QWidget

from app.ui.responsive.breakpoints import (
    DENSITY_COMFORTABLE,
    DENSITY_COMPACT,
    DENSITY_COZY,
    SIDEBAR_DRAWER,
    SIDEBAR_FULL,
    SIDEBAR_ICONS,
    SIDEBAR_WIDTH_FULL,
    SIDEBAR_WIDTH_ICONS,
)
from app.ui.responsive.layout import LayoutEngine
from app.ui.responsive.table_manager import (
    CLIENT_COLUMNS,
    ColumnSpec,
    EXPENSE_COLUMNS,
    PRODUCT_COLUMNS,
    PRODUCT_COLUMNS_MAQUIS,
    STOCK_HISTORY_COLUMNS,
    SUPPLIER_COLUMNS,
    TableColumnController,
    apply_column_priorities,
    visible_column_indexes,
)
from app.ui.responsive.viewport import LayoutProfile, compute_profile


def apply_generic_responsiveness(page: QWidget, state) -> None:
    """Branche ``page`` sur ``state.layout_changed`` avec un comportement générique.

    Filet de sécurité minimal pour les pages qui n'ont pas (encore) leur
    propre logique responsive : marges selon la densité, tables qui ne
    débordent jamais de la fenêtre. Sans danger à appeler en plus d'une
    logique responsive déjà existante sur la page (pos_page, products_page...).
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
    page._generic_responsive_handler = _on_layout_changed


__all__ = [
    "CLIENT_COLUMNS",
    "ColumnSpec",
    "DENSITY_COMFORTABLE",
    "DENSITY_COMPACT",
    "DENSITY_COZY",
    "EXPENSE_COLUMNS",
    "LayoutEngine",
    "LayoutProfile",
    "PRODUCT_COLUMNS",
    "PRODUCT_COLUMNS_MAQUIS",
    "SIDEBAR_DRAWER",
    "SIDEBAR_FULL",
    "SIDEBAR_ICONS",
    "SIDEBAR_WIDTH_FULL",
    "SIDEBAR_WIDTH_ICONS",
    "STOCK_HISTORY_COLUMNS",
    "SUPPLIER_COLUMNS",
    "TableColumnController",
    "apply_column_priorities",
    "apply_generic_responsiveness",
    "compute_profile",
    "visible_column_indexes",
]
