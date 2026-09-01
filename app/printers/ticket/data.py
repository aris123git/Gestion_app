"""Données métier d'un ticket — indépendantes de la présentation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class TicketLineItem:
    name: str
    quantity: float
    unit_price: float
    line_total: float


@dataclass(frozen=True)
class TicketPaymentLine:
    method: str
    amount: float


@dataclass
class TicketData:
    """Snapshot imprimable d'une vente (ou d'un aperçu)."""

    ticket_number: str
    moment: datetime
    cashier_name: str = ""
    client_name: str = ""
    client_id: Optional[int] = None
    items: list[TicketLineItem] = field(default_factory=list)
    subtotal: float = 0.0
    discount: float = 0.0
    total: float = 0.0
    amount_received: float = 0.0
    change_due: float = 0.0
    payments: list[TicketPaymentLine] = field(default_factory=list)
    # Commerce
    shop_name: str = "Commerce"
    shop_address: str = ""
    shop_phone: str = ""
    currency: str = "FCFA"
    logo_path: str = ""
    footer: str = "Merci de votre visite"
    vat_rate: float = 0.0

    @property
    def has_discount(self) -> bool:
        return float(self.discount or 0) > 0.01

    @property
    def has_vat(self) -> bool:
        return float(self.vat_rate or 0) > 0.01

    @property
    def vat_amount(self) -> float:
        if not self.has_vat:
            return 0.0
        rate = float(self.vat_rate)
        total_ttc = float(self.total or 0)
        return round(total_ttc * rate / (100 + rate), 2)

    @property
    def total_ht(self) -> float:
        return round(float(self.total or 0) - self.vat_amount, 2)

    @classmethod
    def from_sale(cls, sale, shop=None, *, vat_rate: float | None = None) -> "TicketData":
        from app.services import settings_service

        shop = shop or settings_service.get_shop_info()
        if vat_rate is None:
            vat_rate = settings_service.get_vat_rate()
        items = [
            TicketLineItem(
                name=str(getattr(it, "product_name", "") or ""),
                quantity=float(getattr(it, "quantity", 0) or 0),
                unit_price=float(getattr(it, "unit_price", 0) or 0),
                line_total=float(getattr(it, "line_total", 0) or 0),
            )
            for it in (sale.items or [])
        ]
        payments = [
            TicketPaymentLine(
                method=str(getattr(pay, "method", "") or "Espèces"),
                amount=float(getattr(pay, "amount", 0) or 0),
            )
            for pay in (getattr(sale, "payments", None) or [])
        ]
        return cls(
            ticket_number=str(getattr(sale, "ticket_number", "") or ""),
            moment=getattr(sale, "date", None) or datetime.now(),
            cashier_name=str(getattr(sale, "cashier_name", "") or ""),
            client_name=str(getattr(sale, "client_name", "") or ""),
            client_id=getattr(sale, "client_id", None),
            items=items,
            subtotal=float(getattr(sale, "subtotal", 0) or 0),
            discount=float(getattr(sale, "discount", 0) or 0),
            total=float(getattr(sale, "total", 0) or 0),
            amount_received=float(getattr(sale, "amount_received", 0) or 0),
            change_due=float(getattr(sale, "change_due", 0) or 0),
            payments=payments,
            shop_name=str(getattr(shop, "name", None) or "Commerce"),
            shop_address=str(getattr(shop, "address", None) or ""),
            shop_phone=str(getattr(shop, "phone", None) or ""),
            currency=str(getattr(shop, "currency", None) or "FCFA"),
            logo_path=str(getattr(shop, "logo_path", None) or ""),
            footer=str(
                getattr(shop, "ticket_footer", None) or "Merci de votre visite"
            ),
            vat_rate=float(vat_rate or 0),
        )


def sample_ticket_data() -> TicketData:
    """Données fictives pour les aperçus de designs dans les paramètres."""
    return TicketData(
        ticket_number="T-42",
        moment=datetime(2026, 9, 1, 14, 30),
        cashier_name="Admin",
        items=[
            TicketLineItem("Café express", 2, 500, 1000),
            TicketLineItem("Croissant", 1, 300, 300),
        ],
        subtotal=1300,
        discount=0,
        total=1300,
        amount_received=1300,
        change_due=0,
        payments=[TicketPaymentLine("Espèces", 1300)],
        shop_name="Café du Port",
        shop_address="12 rue X",
        shop_phone="0600000000",
        currency="FCFA",
        footer="Merci de votre visite",
        vat_rate=0,
    )
