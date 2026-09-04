"""Lignes stylées pour aperçu texte et ESC/POS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass
class StyledLine:
    text: str
    bold: bool = False
    double_height: bool = False
    double_width: bool = False
    align: str = "left"  # left | center | right


def lines_to_text(lines: Iterable[StyledLine], width: int) -> str:
    """Aperçu monospace (gras / double taille non visibles en texte brut)."""
    out: list[str] = []
    for line in lines:
        raw = line.text or ""
        if line.align == "center":
            out.append(raw[:width].center(width))
        elif line.align == "right":
            out.append(raw[:width].rjust(width))
        else:
            out.append(raw[:width])
    return "\n".join(out)


def lines_to_escpos_bytes(
    lines: Iterable[StyledLine],
    *,
    feed_lines: int = 5,
    cut_mode: str = "full",
    logo_path: Optional[str] = None,
    paper: str = "80mm",
    include_logo: bool = True,
    profile=None,
) -> bytes:
    """Construit un flux ESC/POS à partir de lignes stylées.

    Utilise le profil imprimante (codepage + largeur) via ``escpos_encoder``
    pour éviter l'UTF-8 brut et les glyphes asiatiques incorrects.
    """
    from app.printers.escpos_encoder import build_escpos_document
    from app.printers.printer_profile import resolve_printer_profile

    resolved = profile or resolve_printer_profile(paper=paper)
    return build_escpos_document(
        list(lines),
        resolved,
        feed_lines=feed_lines,
        cut_mode=cut_mode,
        logo_path=logo_path,
        paper=paper or resolved.paper_width,
        include_logo=include_logo,
        styled=True,
    )
