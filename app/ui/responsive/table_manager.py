"""Gestionnaire de colonnes de tableau par priorité d'affichage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from PySide6.QtWidgets import QHeaderView, QTableWidget


@dataclass(frozen=True)
class ColumnSpec:
    """Métadonnée d'une colonne : clé, priorité (1 = essentielle), largeur mini."""

    key: str
    priority: int
    min_width: int = 96
    stretch: bool = False


def visible_column_indexes(
    columns: Sequence[ColumnSpec],
    available_width: int,
) -> List[int]:
    """
    Décide quelles colonnes afficher selon l'espace restant.

    Algorithme :
      1. Toujours tenter la priorité 1
      2. Si de la place reste → priorité 2, puis 3, etc.
      3. Une colonne dont min_width ne rentre pas est masquée
         (sauf si c'est la seule colonne restante de priorité 1).
    """
    if not columns:
        return []
    budget = max(0, int(available_width))
    by_priority: dict[int, list[tuple[int, ColumnSpec]]] = {}
    for index, col in enumerate(columns):
        by_priority.setdefault(col.priority, []).append((index, col))

    chosen: list[int] = []
    used = 0
    for priority in sorted(by_priority.keys()):
        group = by_priority[priority]
        group_width = sum(col.min_width for _, col in group)
        # Priorité 1 : on force au moins une colonne même si budget serré.
        if priority == 1:
            for index, col in group:
                if used + col.min_width <= budget or not chosen:
                    chosen.append(index)
                    used += col.min_width
            continue
        if used + group_width <= budget:
            for index, col in group:
                chosen.append(index)
                used += col.min_width
        else:
            # Ajoute une par une tant que ça rentre.
            for index, col in group:
                if used + col.min_width <= budget:
                    chosen.append(index)
                    used += col.min_width
    return sorted(chosen)


def apply_column_priorities(
    table: QTableWidget,
    columns: Sequence[ColumnSpec],
    available_width: int,
) -> List[int]:
    """Masque / affiche les colonnes et configure le redimensionnement."""
    visible = set(visible_column_indexes(columns, available_width))
    header = table.horizontalHeader()
    stretch_index: Optional[int] = None
    for index, col in enumerate(columns):
        if index >= table.columnCount():
            break
        show = index in visible
        table.setColumnHidden(index, not show)
        if show:
            if col.stretch:
                stretch_index = index
            else:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
                table.setColumnWidth(index, max(col.min_width, table.columnWidth(index)))
    if stretch_index is not None:
        header.setSectionResizeMode(stretch_index, QHeaderView.ResizeMode.Stretch)
    elif visible:
        # Fallback : première colonne visible en stretch.
        first = min(visible)
        header.setSectionResizeMode(first, QHeaderView.ResizeMode.Stretch)
    return sorted(visible)


class TableColumnController:
    """Attache une table à un jeu de colonnes prioritaires et se réapplique."""

    def __init__(
        self,
        table: QTableWidget,
        columns: Sequence[ColumnSpec],
        *,
        width_padding: int = 48,
    ) -> None:
        self.table = table
        self.columns = list(columns)
        self.width_padding = width_padding

    def apply(self, content_width: int) -> List[int]:
        return apply_column_priorities(
            self.table,
            self.columns,
            max(0, int(content_width) - self.width_padding),
        )


# Catalogues de colonnes réutilisables par page (ordre = index colonnes table).
PRODUCT_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("name", 1, 160, stretch=True),
    ColumnSpec("category", 2, 110),
    ColumnSpec("barcode", 3, 120),
    ColumnSpec("sale_price", 1, 100),
    ColumnSpec("stock", 1, 80),
    ColumnSpec("unit", 2, 70),
)

CLIENT_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("name", 1, 140, stretch=True),
    ColumnSpec("phone", 1, 110),
    ColumnSpec("address", 3, 120),
    ColumnSpec("debt", 1, 90),
    ColumnSpec("active_debts", 2, 90),
    ColumnSpec("points", 2, 70),
    ColumnSpec("last_visit", 3, 110),
    ColumnSpec("purchases", 4, 80),
)

STOCK_HISTORY_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("date", 1, 120),
    ColumnSpec("user", 2, 100),
    ColumnSpec("product", 1, 140, stretch=True),
    ColumnSpec("movement", 1, 100),
    ColumnSpec("quantity", 1, 80),
    ColumnSpec("stock_after", 2, 90),
    ColumnSpec("supplier", 3, 110),
    ColumnSpec("invoice", 3, 90),
    ColumnSpec("reason", 4, 100),
    ColumnSpec("comment", 4, 100),
)

SUPPLIER_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("name", 1, 140, stretch=True),
    ColumnSpec("phone", 1, 110),
    ColumnSpec("address", 2, 120),
    ColumnSpec("email", 3, 140),
    ColumnSpec("debt", 1, 90),
)

EXPENSE_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("date", 1, 100),
    ColumnSpec("category", 1, 110),
    ColumnSpec("label", 1, 140, stretch=True),
    ColumnSpec("amount", 1, 90),
)


def register_many(
    controllers: Iterable[TableColumnController],
    content_width: int,
) -> None:
    for controller in controllers:
        controller.apply(content_width)
