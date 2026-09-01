"""Tests de compatibilité des anciens layouts (alias → designs)."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")

from app.printers.thermal_printer import (  # noqa: E402
    TICKET_LAYOUT_CLASSIC,
    TICKET_LAYOUT_COMPACT,
    TICKET_LAYOUT_KITCHEN,
    TICKET_LAYOUT_TABLE,
    render_ticket_text,
)


def _sale():
    item = SimpleNamespace(
        product_name="Jus d'orange",
        quantity=2,
        unit_price=500,
        line_total=1000,
    )
    return SimpleNamespace(
        ticket_number="T-TEST-1",
        date=None,
        cashier_name="Admin",
        client_id=None,
        client_name="",
        items=[item],
        subtotal=1000,
        discount=0,
        total=1000,
        amount_received=1000,
        change_due=0,
        payments=[SimpleNamespace(method="Espèces", amount=1000)],
    )


def _shop():
    return SimpleNamespace(
        name="Boutique Test",
        address="",
        phone="",
        currency="FCFA",
        logo_path="",
        ticket_footer="Merci",
    )


class TicketLayoutCompatTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["GESTION_DATA_DIR"] = tempfile.mkdtemp(prefix="ticket_layout_")
        from app.database.connection import init_database
        from app.database.seed import seed_all

        init_database()
        seed_all()

    def test_classic_and_aliases_58_80(self) -> None:
        sale = _sale()
        shop = _shop()
        for paper in ("58mm", "80mm"):
            classic = render_ticket_text(
                sale, shop, paper=paper, layout=TICKET_LAYOUT_CLASSIC
            )
            table = render_ticket_text(
                sale, shop, paper=paper, layout=TICKET_LAYOUT_TABLE
            )
            compact = render_ticket_text(
                sale, shop, paper=paper, layout=TICKET_LAYOUT_COMPACT
            )
            kitchen = render_ticket_text(
                sale, shop, paper=paper, layout=TICKET_LAYOUT_KITCHEN
            )
            self.assertIn("Jus", classic)
            self.assertIn("TOTAL", classic)
            self.assertTrue("TICKET" in table or "Jus" in table)
            self.assertTrue("2" in compact and ("Jus" in compact or "jus" in compact.lower()))
            self.assertIn("A SERVIR", kitchen)
            self.assertNotIn("FCFA", kitchen)
            width = 32 if paper == "58mm" else 48
            for text in (classic, table, compact, kitchen):
                for line in text.splitlines():
                    self.assertLessEqual(len(line), width + 2, msg=repr(line))

    def test_kitchen_no_prices(self) -> None:
        kitchen = render_ticket_text(
            _sale(), _shop(), paper="80mm", layout=TICKET_LAYOUT_KITCHEN
        )
        self.assertIn("A SERVIR", kitchen)
        self.assertNotIn("TOTAL", kitchen)
        self.assertNotIn("FCFA", kitchen)


if __name__ == "__main__":
    unittest.main()
