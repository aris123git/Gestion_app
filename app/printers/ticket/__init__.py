"""Bibliothèque de designs de tickets thermiques.

Architecture : TicketData → TicketDesign → rendu (texte / ESC/POS) → ThermalPrinter.
"""

from app.printers.ticket.data import TicketData, sample_ticket_data
from app.printers.ticket.options import TicketOptions, load_ticket_options
from app.printers.ticket.registry import (
    CLIENT_DESIGNS,
    KITCHEN_DESIGNS,
    get_design,
    list_designs,
    resolve_client_design_id,
    resolve_kitchen_design_id,
)
from app.printers.ticket.renderer import (
    render_sale_ticket,
    render_ticket,
    render_ticket_preview,
)

__all__ = [
    "TicketData",
    "TicketOptions",
    "sample_ticket_data",
    "load_ticket_options",
    "CLIENT_DESIGNS",
    "KITCHEN_DESIGNS",
    "get_design",
    "list_designs",
    "resolve_client_design_id",
    "resolve_kitchen_design_id",
    "render_ticket",
    "render_sale_ticket",
    "render_ticket_preview",
]
