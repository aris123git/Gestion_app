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
) -> bytes:
    """Construit un flux ESC/POS à partir de lignes stylées."""
    feed_lines = max(0, int(feed_lines))
    cut_map = {"full": "FULL", "partial": "PART"}
    try:
        from escpos.printer import Dummy

        dummy = Dummy()
        if include_logo and logo_path:
            try:
                from app.printers.thermal_printer import _load_logo_image

                logo = _load_logo_image(logo_path, paper)
                if logo is not None:
                    dummy.set(align="center")
                    dummy.image(logo)
                    dummy.set(align="left")
            except Exception:
                pass

        for line in lines:
            align = {"left": "left", "center": "center", "right": "right"}.get(
                line.align, "left"
            )
            w = 2 if line.double_width else 1
            h = 2 if line.double_height else 1
            dummy.set(align=align, bold=bool(line.bold), width=w, height=h)
            text = line.text or ""
            if not text.endswith("\n"):
                text = text + "\n"
            dummy.text(text)

        dummy.set(align="left", bold=False, width=1, height=1)
        if feed_lines:
            dummy.text("\n" * feed_lines)
        if cut_mode != "none":
            mode = cut_map.get(cut_mode, "FULL")
            try:
                dummy.cut(mode=mode)
            except Exception:
                try:
                    dummy.cut()
                except Exception:
                    pass
        return dummy.output
    except Exception:
        text = lines_to_text(lines, 48)
        data = text.encode("utf-8", errors="replace")
        data += b"\n" * feed_lines
        if cut_mode != "none":
            data += b"\x1d\x56\x00"
        return data
