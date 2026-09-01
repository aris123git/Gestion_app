"""Designs cuisine / bon serveur — sans prix ni paiement."""

from __future__ import annotations

from app.printers.ticket.data import TicketData
from app.printers.ticket.designs.base import (
    L,
    TicketDesign,
    item_qty_name,
    meta_bits,
    qty_label,
    separator,
)
from app.printers.ticket.layout import row
from app.printers.ticket.options import TicketOptions
from app.printers.ticket.styled import StyledLine


class CuisineDesign(TicketDesign):
    id = "cuisine"
    label = "Cuisine"
    category = "kitchen"
    description = "Lecture rapide cuisine — gros caractères, sans prix."
    uses_logo = False
    preferred_feed = 3

    def render(self, data: TicketData, opts: TicketOptions, width: int) -> list[StyledLine]:
        lines: list[StyledLine] = []
        m = meta_bits(data, opts)
        title = f"COMMANDE {m['number']}" if m["number"] else "COMMANDE"
        lines.append(
            L(title, bold=True, double_height=True, double_width=True, align="center")
        )
        if m["time"]:
            lines.append(L(m["time"], bold=True, align="center"))
        lines.append(separator(width, "-"))
        lines.extend(opts.gap())
        for item in data.items:
            q = qty_label(item)
            name = (item.name or "").strip().upper()
            lines.append(L(f"{q} × {name}", bold=True, double_height=True))
            lines.extend(opts.gap())
        return lines


class CuisineCompactDesign(TicketDesign):
    id = "cuisine_compact"
    label = "Cuisine compact"
    category = "kitchen"
    description = "Cuisine lisible, un peu plus économique en papier."
    uses_logo = False
    preferred_feed = 2

    def render(self, data: TicketData, opts: TicketOptions, width: int) -> list[StyledLine]:
        lines: list[StyledLine] = []
        m = meta_bits(data, opts)
        title = f"CMD {m['number']}" if m["number"] else "CMD"
        head = row(title, m["time"], width) if m["time"] else title
        lines.append(L(head, bold=True))
        lines.append(separator(width))
        for item in data.items:
            left = f"{qty_label(item)}x {(item.name or '').strip().upper()}"
            lines.append(L(left[:width], bold=True))
        return lines


class ServeurDesign(TicketDesign):
    id = "serveur"
    label = "Bon serveur"
    category = "kitchen"
    description = "Pour le serveur : quoi servir, sans prix."
    uses_logo = False
    preferred_feed = 2

    def render(self, data: TicketData, opts: TicketOptions, width: int) -> list[StyledLine]:
        # Lisibilité prioritaire (espacement normal même si densité compacte globale).
        lines: list[StyledLine] = []
        lines.append(L("A SERVIR", bold=True, double_height=True, align="center"))
        lines.extend(opts.gap()[:1] or [L("")])
        m = meta_bits(data, opts)
        lines.append(L(row(m["number"], m["time"], width)))
        lines.append(separator(width, "-"))
        lines.extend(opts.gap()[:1])
        for item in data.items:
            lines.append(L(item_qty_name(item, upper=True), bold=True))
        lines.extend(opts.gap()[:1])
        return lines


# Alias historique « kitchen » → serveur (compatibilité settings).
class KitchenLegacyDesign(ServeurDesign):
    id = "kitchen"
    label = "Bon serveur (ancien)"
    description = "Alias de compatibilité vers Bon serveur."


KITCHEN_DESIGN_CLASSES = (
    ServeurDesign,
    CuisineDesign,
    CuisineCompactDesign,
    KitchenLegacyDesign,
)
