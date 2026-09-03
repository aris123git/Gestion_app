"""Options d'affichage et densité — personnalisation légère des designs."""

from __future__ import annotations

from dataclasses import dataclass

from app.services import settings_service

DENSITY_COMPACT = "compact"
DENSITY_NORMAL = "normal"
DENSITY_AIRY = "airy"
DENSITIES = (DENSITY_COMPACT, DENSITY_NORMAL, DENSITY_AIRY)

HEADER_ALIGN_LEFT = "left"
HEADER_ALIGN_CENTER = "center"

SETTING_KITCHEN_ENABLED = "ticket_kitchen_enabled"


@dataclass
class TicketOptions:
    """Préférences d'affichage (ne changent pas la logique métier)."""

    density: str = DENSITY_NORMAL
    show_shop_name: bool = True
    show_phone: bool = True
    show_address: bool = True
    show_logo: bool = True
    header_align: str = HEADER_ALIGN_CENTER
    show_number: bool = True
    show_date: bool = True
    show_time: bool = True
    show_cashier: bool = True
    show_subtotal: bool = True
    show_discount: bool = True
    show_tax: bool = True
    show_total: bool = True
    show_received: bool = True
    show_change: bool = True
    hide_zero_change: bool = True
    show_payment: bool = True
    show_footer: bool = True
    # Gras ESC/POS pour montants (facture tableau / lecture rapide).
    bold_prices: bool = True
    bold_total: bool = True

    @property
    def blank_lines(self) -> int:
        """Lignes vides entre sections selon la densité."""
        if self.density == DENSITY_COMPACT:
            return 0
        if self.density == DENSITY_AIRY:
            return 2
        return 1

    def gap(self) -> list:
        """Retourne 0–2 lignes vides (StyledLine) selon densité."""
        from app.printers.ticket.styled import StyledLine

        n = self.blank_lines
        return [StyledLine("")] * n if n else []


def _flag(key: str, default: bool = True) -> bool:
    raw = settings_service.get_setting(key, "1" if default else "0")
    return str(raw).strip() not in ("0", "false", "False", "")


def load_ticket_options() -> TicketOptions:
    density = settings_service.get_setting("ticket_density", DENSITY_NORMAL)
    if density not in DENSITIES:
        density = DENSITY_NORMAL
    align = settings_service.get_setting("ticket_header_align", HEADER_ALIGN_CENTER)
    if align not in (HEADER_ALIGN_LEFT, HEADER_ALIGN_CENTER):
        align = HEADER_ALIGN_CENTER
    return TicketOptions(
        density=density,
        show_shop_name=_flag("ticket_show_shop_name", True),
        show_phone=_flag("ticket_show_phone", True),
        show_address=_flag("ticket_show_address", True),
        show_logo=_flag("ticket_show_logo", True),
        header_align=align,
        show_number=_flag("ticket_show_number", True),
        show_date=_flag("ticket_show_date", True),
        show_time=_flag("ticket_show_time", True),
        show_cashier=_flag("ticket_show_cashier", True),
        show_subtotal=_flag("ticket_show_subtotal", True),
        show_discount=_flag("ticket_show_discount", True),
        show_tax=_flag("ticket_show_tax", True),
        show_total=_flag("ticket_show_total", True),
        show_received=_flag("ticket_show_received", True),
        show_change=_flag("ticket_show_change", True),
        hide_zero_change=_flag("ticket_hide_zero_change", True),
        show_payment=_flag("ticket_show_payment", True),
        show_footer=_flag("ticket_show_footer", True),
        bold_prices=_flag("ticket_bold_prices", True),
        bold_total=_flag("ticket_bold_total", True),
    )


def save_ticket_options(opts: TicketOptions) -> None:
    def put(key: str, value: bool | str) -> None:
        if isinstance(value, bool):
            settings_service.set_setting(key, "1" if value else "0")
        else:
            settings_service.set_setting(key, str(value))

    put("ticket_density", opts.density)
    put("ticket_show_shop_name", opts.show_shop_name)
    put("ticket_show_phone", opts.show_phone)
    put("ticket_show_address", opts.show_address)
    put("ticket_show_logo", opts.show_logo)
    put("ticket_header_align", opts.header_align)
    put("ticket_show_number", opts.show_number)
    put("ticket_show_date", opts.show_date)
    put("ticket_show_time", opts.show_time)
    put("ticket_show_cashier", opts.show_cashier)
    put("ticket_show_subtotal", opts.show_subtotal)
    put("ticket_show_discount", opts.show_discount)
    put("ticket_show_tax", opts.show_tax)
    put("ticket_show_total", opts.show_total)
    put("ticket_show_received", opts.show_received)
    put("ticket_show_change", opts.show_change)
    put("ticket_hide_zero_change", opts.hide_zero_change)
    put("ticket_show_payment", opts.show_payment)
    put("ticket_show_footer", opts.show_footer)
    put("ticket_bold_prices", opts.bold_prices)
    put("ticket_bold_total", opts.bold_total)


def is_kitchen_ticket_enabled() -> bool:
    """Indique si le bon serveur / cuisine est activé dans les paramètres."""
    raw = settings_service.get_setting(SETTING_KITCHEN_ENABLED, "1")
    return str(raw).strip() not in ("0", "false", "False", "")


def set_kitchen_ticket_enabled(enabled: bool) -> None:
    settings_service.set_setting(SETTING_KITCHEN_ENABLED, "1" if enabled else "0")
