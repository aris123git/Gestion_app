"""Moteur responsive centralisé (viewport, layout, tables prioritaires)."""

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
    STOCK_HISTORY_COLUMNS,
    SUPPLIER_COLUMNS,
    TableColumnController,
    apply_column_priorities,
    visible_column_indexes,
)
from app.ui.responsive.viewport import LayoutProfile, compute_profile

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
    "SIDEBAR_DRAWER",
    "SIDEBAR_FULL",
    "SIDEBAR_ICONS",
    "SIDEBAR_WIDTH_FULL",
    "SIDEBAR_WIDTH_ICONS",
    "STOCK_HISTORY_COLUMNS",
    "SUPPLIER_COLUMNS",
    "TableColumnController",
    "apply_column_priorities",
    "compute_profile",
    "visible_column_indexes",
]
