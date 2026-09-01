"""Rendu d'un ticket : données + design + options → texte / lignes stylées."""

from __future__ import annotations

from typing import Optional

from app.printers.ticket.data import TicketData
from app.printers.ticket.options import TicketOptions, load_ticket_options
from app.printers.ticket.registry import get_design, resolve_design_id
from app.printers.ticket.styled import StyledLine, lines_to_text


WIDTH_CHARS = {"58mm": 32, "80mm": 48, "demi-A4": 72}


def paper_width(paper: str) -> int:
    from app.printers.half_a4_invoice import HALF_A4_WIDTH_CHARS, is_half_a4

    if is_half_a4(paper):
        return HALF_A4_WIDTH_CHARS
    return WIDTH_CHARS.get(paper, 48)


def render_ticket(
    data: TicketData,
    *,
    design_id: Optional[str] = None,
    role: str = "client",
    options: Optional[TicketOptions] = None,
    paper: str = "80mm",
    width: Optional[int] = None,
) -> list[StyledLine]:
    """Retourne les lignes stylées pour un design donné."""
    opts = options or load_ticket_options()
    resolved = resolve_design_id(design_id, role=role)
    # Demi-A4 : forcer un design client classique (PDF a son propre moteur).
    from app.printers.half_a4_invoice import is_half_a4

    if is_half_a4(paper) and role == "client":
        resolved = "classic"
    design = get_design(resolved)
    w = width if width is not None else paper_width(paper)
    return design.render(data, opts, w)


def render_ticket_text_from_data(
    data: TicketData,
    *,
    design_id: Optional[str] = None,
    role: str = "client",
    options: Optional[TicketOptions] = None,
    paper: str = "80mm",
) -> str:
    w = paper_width(paper)
    lines = render_ticket(
        data, design_id=design_id, role=role, options=options, paper=paper, width=w
    )
    text = lines_to_text(lines, w)
    # Deux lignes vides en fin (avance visuelle aperçu), sauf designs cuisine.
    design = get_design(resolve_design_id(design_id, role=role))
    if design.category != "kitchen":
        text = text.rstrip("\n") + "\n\n"
    return text


def render_sale_ticket(
    sale,
    shop=None,
    *,
    paper: str = "80mm",
    design_id: Optional[str] = None,
    role: str = "client",
    options: Optional[TicketOptions] = None,
) -> str:
    """Facade : vente ORM → texte ticket."""
    data = TicketData.from_sale(sale, shop)
    return render_ticket_text_from_data(
        data, design_id=design_id, role=role, options=options, paper=paper
    )


def render_ticket_preview(
    design_id: str,
    *,
    paper: str = "80mm",
    options: Optional[TicketOptions] = None,
) -> str:
    """Aperçu avec données fictives (cartes paramètres)."""
    from app.printers.ticket.data import sample_ticket_data

    data = sample_ticket_data()
    design = get_design(design_id)
    role = "kitchen" if design.category == "kitchen" else "client"
    if options is None:
        try:
            options = load_ticket_options()
        except Exception:
            options = TicketOptions()
    return render_ticket_text_from_data(
        data, design_id=design_id, role=role, options=options, paper=paper
    )


# Alias public
render_ticket_as_text = render_ticket_text_from_data
