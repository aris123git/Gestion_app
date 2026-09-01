"""Classe de base et utilitaires partagés des designs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from app.printers.ticket.data import TicketData, TicketLineItem
from app.printers.ticket.layout import fit_left_right, row, sep, wrap_text
from app.printers.ticket.options import HEADER_ALIGN_LEFT, TicketOptions
from app.printers.ticket.styled import StyledLine
from app.utils.helpers import format_money, format_quantity

MONTHS_FR = (
    "",
    "JANVIER",
    "FÉVRIER",
    "MARS",
    "AVRIL",
    "MAI",
    "JUIN",
    "JUILLET",
    "AOÛT",
    "SEPTEMBRE",
    "OCTOBRE",
    "NOVEMBRE",
    "DÉCEMBRE",
)


class TicketDesign(ABC):
    """Présentation visuelle d'un TicketData (sans logique métier)."""

    id: ClassVar[str] = ""
    label: ClassVar[str] = ""
    category: ClassVar[str] = "client"  # client | kitchen
    description: ClassVar[str] = ""
    uses_logo: ClassVar[bool] = True
    preferred_feed: ClassVar[int | None] = None

    @abstractmethod
    def render(
        self, data: TicketData, opts: TicketOptions, width: int
    ) -> list[StyledLine]:
        raise NotImplementedError


def L(
    text: str,
    *,
    bold: bool = False,
    double_height: bool = False,
    double_width: bool = False,
    align: str = "left",
) -> StyledLine:
    return StyledLine(
        text=text,
        bold=bold,
        double_height=double_height,
        double_width=double_width,
        align=align,
    )


def money(amount: float, currency: str, *, with_currency: bool = True) -> str:
    if with_currency:
        return format_money(amount, currency)
    try:
        value = float(amount)
    except (TypeError, ValueError):
        value = 0.0
    return f"{value:,.0f}".replace(",", " ")


def qty_label(item: TicketLineItem) -> str:
    return format_quantity(item.quantity)


def item_qty_name(item: TicketLineItem, *, upper: bool = False) -> str:
    name = (item.name or "").strip()
    if upper:
        name = name.upper()
    return f"{qty_label(item)} × {name}"


def header_lines(
    data: TicketData,
    opts: TicketOptions,
    width: int,
    *,
    name_phone_same_line: bool = False,
    phone_address_same_line: bool = False,
    name_bold: bool = False,
    name_upper: bool = False,
    name_double: bool = False,
) -> list[StyledLine]:
    """En-tête commerce selon options."""
    lines: list[StyledLine] = []
    align = "left" if opts.header_align == HEADER_ALIGN_LEFT else "center"
    name = (data.shop_name or "Commerce").strip()
    if name_upper:
        name = name.upper()
    phone = (data.shop_phone or "").strip()
    address = (data.shop_address or "").strip()

    phone_on_name_line = False
    if opts.show_shop_name and name:
        if name_phone_same_line and opts.show_phone and phone:
            for piece in fit_left_right(name, f"Tel: {phone}", width):
                lines.append(L(piece, bold=name_bold))
            phone_on_name_line = True
        else:
            lines.append(
                L(
                    name,
                    bold=name_bold,
                    double_height=name_double,
                    double_width=name_double,
                    align=align,
                )
            )

    if phone_address_same_line and opts.show_phone and opts.show_address and phone and address:
        for w in wrap_text(f"Tel: {phone} · {address}", width):
            lines.append(L(w, align=align))
    else:
        if opts.show_address and address:
            for w in wrap_text(address, width):
                lines.append(L(w, align=align))
        if opts.show_phone and phone and not phone_on_name_line:
            lines.append(L(f"Tel: {phone}", align=align))

    return lines


def meta_bits(data: TicketData, opts: TicketOptions) -> dict:
    return {
        "number": data.ticket_number if opts.show_number else "",
        "date": data.moment.strftime("%d/%m/%Y") if opts.show_date else "",
        "date_short": data.moment.strftime("%d/%m") if opts.show_date else "",
        "date_long": (
            f"{data.moment.day:02d} {MONTHS_FR[data.moment.month]} {data.moment.year}"
            if opts.show_date
            else ""
        ),
        "time": data.moment.strftime("%H:%M") if opts.show_time else "",
        "cashier": data.cashier_name if opts.show_cashier else "",
    }


def should_show_change(data: TicketData, opts: TicketOptions) -> bool:
    if not opts.show_change:
        return False
    if opts.hide_zero_change and float(data.change_due or 0) < 0.01:
        return False
    return True


def totals_block(
    data: TicketData,
    opts: TicketOptions,
    width: int,
    *,
    total_bold: bool = True,
    total_double: bool = False,
    total_alone: bool = False,
    currency_on_amounts: bool = True,
) -> list[StyledLine]:
    cur = data.currency
    lines: list[StyledLine] = []
    if opts.show_subtotal:
        lines.append(
            L(
                row(
                    "Sous-total",
                    money(data.subtotal, cur, with_currency=currency_on_amounts),
                    width,
                )
            )
        )
    if opts.show_discount and data.has_discount:
        lines.append(
            L(
                row(
                    "Remise",
                    money(data.discount, cur, with_currency=currency_on_amounts),
                    width,
                )
            )
        )
    if opts.show_tax and data.has_vat:
        lines.append(
            L(
                row(
                    f"dont TVA {data.vat_rate:g}%",
                    money(data.vat_amount, cur, with_currency=currency_on_amounts),
                    width,
                )
            )
        )
    if opts.show_total:
        if total_alone:
            lines.append(L("TOTAL", bold=total_bold))
            lines.append(
                L(
                    money(data.total, cur, with_currency=True),
                    bold=total_bold,
                    double_height=total_double,
                    double_width=total_double,
                )
            )
        else:
            lines.append(
                L(
                    row("TOTAL", money(data.total, cur), width),
                    bold=total_bold,
                    double_height=total_double,
                    double_width=total_double,
                )
            )
    if opts.show_received:
        lines.append(
            L(
                row(
                    "Reçu",
                    money(data.amount_received, cur, with_currency=currency_on_amounts),
                    width,
                )
            )
        )
    if should_show_change(data, opts):
        lines.append(
            L(
                row(
                    "Monnaie",
                    money(data.change_due, cur, with_currency=currency_on_amounts),
                    width,
                )
            )
        )
    return lines


def payments_block(
    data: TicketData, opts: TicketOptions, width: int, *, inline: bool = False
) -> list[StyledLine]:
    if not opts.show_payment or not data.payments:
        return []
    if inline and len(data.payments) == 1:
        pay = data.payments[0]
        return [L(f"{pay.method.upper()} · {money(pay.amount, data.currency)}")]
    return [
        L(row(pay.method, money(pay.amount, data.currency), width))
        for pay in data.payments
    ]


def footer_block(data: TicketData, opts: TicketOptions, width: int) -> list[StyledLine]:
    if not opts.show_footer:
        return []
    msg = (data.footer or "").strip()
    if not msg:
        return []
    return [L(msg, align="center")]


def separator(width: int, char: str = "-") -> StyledLine:
    return L(sep(char, width))
