"""Sélection multiple : supprimer / annuler plusieurs lignes d'un coup, avec une seule confirmation."""
from __future__ import annotations

from typing import Callable, Sequence

from PySide6.QtWidgets import QAbstractItemView, QTableWidget

from app.i18n import t
from app.ui.widgets.helpers import confirm, info


def enable_multi(table: QTableWidget) -> None:
    """Ctrl/Maj + clic pour choisir plusieurs lignes."""
    table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)


def selected_rows(table: QTableWidget) -> list[int]:
    return sorted({i.row() for i in table.selectionModel().selectedRows()}) if table.selectionModel() else []


def run_batch(parent, question: str, items: Sequence[tuple[int, str]], action: Callable[[int], object], done_text: str = "fait") -> int:
    """Demande confirmation (« question » contient {n}), exécute `action(id)` pour chaque ligne.

    Les lignes impossibles (ValueError...) sont signalées, les autres sont faites. Retourne le nombre réussi."""
    if not items or (question and not confirm(parent, question.format(n=len(items)))):
        return 0
    done, failed = 0, []
    for item_id, label in items:
        try:
            action(item_id)
            done += 1
        except Exception as exc:  # une ligne refusée n'arrête pas les autres
            failed.append(f"• {label} : {exc}")
    msg = f"{done} {done_text}."
    if failed:
        msg += "\n\n" + t("Non faits :") + "\n" + "\n".join(failed[:12]) + ("\n…" if len(failed) > 12 else "")
    info(parent, msg)
    return done
