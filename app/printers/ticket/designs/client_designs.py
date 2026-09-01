"""Designs client : classique, moderne, compact, élégant, restaurant, minimal, bold, terminal."""

from __future__ import annotations

from app.printers.ticket.data import TicketData
from app.printers.ticket.designs.base import (
    L,
    TicketDesign,
    footer_block,
    header_lines,
    item_qty_name,
    meta_bits,
    money,
    payments_block,
    qty_label,
    separator,
    should_show_change,
    totals_block,
)
from app.printers.ticket.layout import fit_left_right, row
from app.printers.ticket.options import TicketOptions
from app.printers.ticket.styled import StyledLine


class ClassicDesign(TicketDesign):
    id = "classic"
    label = "Classique"
    description = "Professionnel, sobre, très lisible."

    def render(self, data: TicketData, opts: TicketOptions, width: int) -> list[StyledLine]:
        lines: list[StyledLine] = []
        lines.extend(
            header_lines(data, opts, width, name_phone_same_line=True, name_upper=True)
        )
        lines.append(separator(width, "-"))
        m = meta_bits(data, opts)
        meta_parts = [p for p in (m["number"], m["date_short"], m["time"]) if p]
        if meta_parts:
            lines.append(L(" · ".join(meta_parts)))
        if m["cashier"]:
            lines.append(L(f"Caissier: {m['cashier']}"))
        lines.extend(opts.gap())
        for item in data.items:
            left = item_qty_name(item)
            right = money(item.line_total, data.currency)
            for piece in fit_left_right(left, right, width):
                lines.append(L(piece))
        lines.append(separator(width, "-"))
        # Classique : total dominant, sous-total optionnel plus discret.
        slim = TicketOptions(**{**opts.__dict__, "show_subtotal": False, "show_received": False})
        lines.extend(totals_block(data, slim, width, total_bold=True))
        lines.extend(payments_block(data, opts, width))
        if should_show_change(data, opts) and opts.show_change:
            # déjà dans totals si show_received path — classic example shows payment only
            pass
        lines.append(separator(width, "-"))
        # Footer court type « Merci ! »
        if opts.show_footer:
            msg = (data.footer or "Merci !").strip()
            if "Merci de votre visite" in msg:
                msg = "Merci !"
            lines.append(L(msg, align="center"))
        return lines


class ModernDesign(TicketDesign):
    id = "modern"
    label = "Moderne"
    description = "Épuré, hiérarchie forte, total dominant."

    def render(self, data: TicketData, opts: TicketOptions, width: int) -> list[StyledLine]:
        lines: list[StyledLine] = []
        lines.extend(
            header_lines(
                data, opts, width, phone_address_same_line=True, name_bold=True
            )
        )
        lines.extend(opts.gap())
        m = meta_bits(data, opts)
        if m["number"] or m["time"]:
            lines.append(L(row(m["number"], m["time"], width)))
        if m["date_long"]:
            lines.append(L(m["date_long"]))
        lines.extend(opts.gap())
        for item in data.items:
            left = item_qty_name(item)
            right = money(item.line_total, data.currency, with_currency=False)
            for piece in fit_left_right(left, right, width):
                lines.append(L(piece))
        lines.extend(opts.gap())
        slim = TicketOptions(
            **{
                **opts.__dict__,
                "show_subtotal": False,
                "show_received": False,
                "show_change": False,
            }
        )
        lines.extend(
            totals_block(data, slim, width, total_bold=True, total_alone=True)
        )
        lines.extend(opts.gap())
        lines.extend(payments_block(data, opts, width, inline=True))
        lines.extend(opts.gap())
        lines.extend(footer_block(data, opts, width))
        return lines


class CompactDesign(TicketDesign):
    id = "compact"
    label = "Compact"
    description = "Économie de papier, toujours lisible."

    def render(self, data: TicketData, opts: TicketOptions, width: int) -> list[StyledLine]:
        # Force densité compacte pour ce design.
        dense = TicketOptions(**{**opts.__dict__, "density": "compact"})
        lines: list[StyledLine] = []
        if dense.show_shop_name:
            lines.append(L((data.shop_name or "")[:width], bold=True, align="center"))
        m = meta_bits(data, dense)
        bits = [p for p in (m["number"], m["time"]) if p]
        if bits:
            lines.append(L(" ".join(bits)))
        for item in data.items:
            left = f"{qty_label(item)}x {(item.name or '').strip()}"
            right = money(item.line_total, data.currency, with_currency=False)
            for piece in fit_left_right(left, right, width):
                lines.append(L(piece))
        if dense.show_total:
            lines.append(L(row("TOTAL", money(data.total, data.currency), width), bold=True))
        lines.extend(payments_block(data, dense, width, inline=True))
        return lines


class ElegantDesign(TicketDesign):
    id = "elegant"
    label = "Élégant"
    description = "Raffiné, espacement maîtrisé, qualité."

    def render(self, data: TicketData, opts: TicketOptions, width: int) -> list[StyledLine]:
        airy = TicketOptions(**{**opts.__dict__, "density": "airy"})
        lines: list[StyledLine] = []
        lines.extend(
            header_lines(data, airy, width, name_bold=True, name_upper=False)
        )
        lines.extend(airy.gap())
        lines.append(separator(width, "-"))
        lines.extend(airy.gap())
        m = meta_bits(data, airy)
        if m["number"]:
            lines.append(L(m["number"], align="center"))
        date_time = "  ·  ".join(p for p in (m["date"], m["time"]) if p)
        if date_time:
            lines.append(L(date_time, align="center"))
        if m["cashier"]:
            lines.append(L(m["cashier"], align="center"))
        lines.extend(airy.gap())
        for item in data.items:
            lines.append(L((item.name or "").strip()))
            detail = f"  {qty_label(item)} × {money(item.unit_price, data.currency)}"
            lines.append(
                L(row(detail, money(item.line_total, data.currency), width))
            )
            lines.extend(airy.gap()[:1])
        lines.append(separator(width, "-"))
        lines.extend(airy.gap())
        lines.extend(totals_block(data, airy, width, total_bold=True))
        lines.extend(payments_block(data, airy, width))
        lines.extend(airy.gap())
        lines.extend(footer_block(data, airy, width))
        return lines


class RestaurantDesign(TicketDesign):
    id = "restaurant"
    label = "Restaurant"
    description = "Cafés, restos, snacks — quantités lisibles."

    def render(self, data: TicketData, opts: TicketOptions, width: int) -> list[StyledLine]:
        lines: list[StyledLine] = []
        lines.extend(
            header_lines(data, opts, width, name_bold=True, name_upper=True, name_double=False)
        )
        lines.append(separator(width))
        m = meta_bits(data, opts)
        if m["number"] or m["time"]:
            lines.append(L(row(f"Cmd {m['number']}", m["time"], width), bold=True))
        if m["cashier"]:
            lines.append(L(f"Serveur: {m['cashier']}"))
        lines.append(separator(width))
        for item in data.items:
            q = qty_label(item)
            name = (item.name or "").strip()
            lines.append(L(f"{q} ×  {name}", bold=True))
            lines.append(L(row("", money(item.line_total, data.currency), width)))
        lines.append(separator(width, "="))
        slim = TicketOptions(**{**opts.__dict__, "show_subtotal": opts.show_subtotal})
        lines.extend(totals_block(data, slim, width, total_bold=True))
        lines.append(separator(width))
        lines.extend(payments_block(data, opts, width))
        lines.extend(opts.gap())
        lines.extend(footer_block(data, opts, width))
        return lines


class MinimalDesign(TicketDesign):
    id = "minimal"
    label = "Minimal"
    description = "Extrêmement épuré, infos essentielles."

    def render(self, data: TicketData, opts: TicketOptions, width: int) -> list[StyledLine]:
        lines: list[StyledLine] = []
        if opts.show_shop_name:
            lines.append(L((data.shop_name or "").strip(), align="center"))
        lines.extend(opts.gap())
        m = meta_bits(data, opts)
        if m["number"]:
            lines.append(L(m["number"]))
        for item in data.items:
            left = item_qty_name(item)
            right = money(item.line_total, data.currency, with_currency=False)
            for piece in fit_left_right(left, right, width):
                lines.append(L(piece))
        lines.extend(opts.gap())
        if opts.show_total:
            lines.append(L(row("Total", money(data.total, data.currency), width)))
        if opts.show_payment and data.payments:
            pay = data.payments[0]
            lines.append(L(pay.method))
        if opts.show_footer and data.footer:
            lines.extend(opts.gap())
            lines.append(L((data.footer or "").strip(), align="center"))
        return lines


class BoldDesign(TicketDesign):
    id = "bold"
    label = "Bold"
    description = "Fort contraste, lecture rapide."
    preferred_feed = 4

    def render(self, data: TicketData, opts: TicketOptions, width: int) -> list[StyledLine]:
        lines: list[StyledLine] = []
        if opts.show_shop_name:
            lines.append(L((data.shop_name or "").upper(), bold=True, align="center"))
        lines.append(separator(width, "="))
        m = meta_bits(data, opts)
        if m["number"]:
            lines.append(
                L(m["number"], bold=True, double_height=True, double_width=True, align="center")
            )
        bits = "  ".join(p for p in (m["date"], m["time"]) if p)
        if bits:
            lines.append(L(bits, align="center", bold=True))
        lines.append(separator(width, "="))
        for item in data.items:
            left = item_qty_name(item, upper=True)
            right = money(item.line_total, data.currency)
            for piece in fit_left_right(left, right, width):
                lines.append(L(piece, bold=True))
        lines.append(separator(width, "="))
        if opts.show_total:
            lines.append(L("TOTAL", bold=True, align="center"))
            lines.append(
                L(
                    money(data.total, data.currency),
                    bold=True,
                    double_height=True,
                    double_width=True,
                    align="center",
                )
            )
        lines.extend(payments_block(data, opts, width))
        lines.extend(footer_block(data, opts, width))
        return lines


class TerminalDesign(TicketDesign):
    id = "terminal"
    label = "Terminal"
    description = "Style caisse / terminal, alignement strict."

    def render(self, data: TicketData, opts: TicketOptions, width: int) -> list[StyledLine]:
        lines: list[StyledLine] = []
        lines.extend(header_lines(data, opts, width, name_upper=True))
        lines.append(separator(width, "="))
        m = meta_bits(data, opts)
        if m["number"]:
            lines.append(L(f"TICKET {m['number']}"))
        if m["date"] or m["time"]:
            lines.append(L(row(m["date"], m["time"], width)))
        if m["cashier"]:
            lines.append(L(f"CAISSIER {m['cashier']}"))
        lines.append(separator(width, "-"))
        # En-tête colonnes
        if width <= 32:
            lines.append(L(f"{'QTE':>4} {'ARTICLE':<12} {'MT':>10}"[:width]))
        else:
            lines.append(L(row("ARTICLE", "QTE     MONTANT", width)))
        lines.append(separator(width, "-"))
        for item in data.items:
            name = (item.name or "").strip()
            q = qty_label(item)
            amt = money(item.line_total, data.currency)
            if width <= 32:
                lines.append(L(name[:width]))
                lines.append(L(row(f"  x{q}", amt, width)))
            else:
                right = f"{q:>4}  {amt:>10}"
                for piece in fit_left_right(name, right, width):
                    lines.append(L(piece))
        lines.append(separator(width, "="))
        lines.extend(totals_block(data, opts, width, total_bold=True))
        lines.append(separator(width, "-"))
        lines.extend(payments_block(data, opts, width))
        lines.append(separator(width, "="))
        lines.extend(footer_block(data, opts, width))
        return lines


CLIENT_DESIGN_CLASSES = (
    ClassicDesign,
    ModernDesign,
    CompactDesign,
    ElegantDesign,
    RestaurantDesign,
    MinimalDesign,
    BoldDesign,
    TerminalDesign,
)
