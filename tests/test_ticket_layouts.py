"""Tests des présentations de ticket thermique."""

from __future__ import annotations

import os
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


class TicketLayoutTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["GESTION_DATA_DIR"] = "/tmp/ticket_layout_test"
        from app.database.connection import init_database
        from app.database.seed import seed_all

        init_database()
        seed_all()

    def test_classic_and_table_58_80(self) -> None:
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
            self.assertIn("Qté", table)
            self.assertIn("2x", compact)
            self.assertIn("A SERVIR", kitchen)
            self.assertIn("2x", kitchen)
            self.assertIn("JUS", kitchen)
            # Bon serveur : court (pas de totaux / adresse / footer).
            self.assertNotIn("TOTAL", kitchen)
            self.assertLess(len(kitchen.splitlines()), len(classic.splitlines()))
            # Largeur respectée approximativement (pas de ligne monstrueuse).
            for text in (classic, table, compact, kitchen):
                width = 32 if paper == "58mm" else 48
                for line in text.splitlines():
                    self.assertLessEqual(len(line), width + 2, msg=repr(line))

    def test_kitchen_shorter_than_verbose_header(self) -> None:
        """Le bon serveur ne doit pas gaspiller de papier (pas de lignes vides)."""
        sale = _sale()
        shop = _shop()
        kitchen = render_ticket_text(
            sale, shop, paper="80mm", layout=TICKET_LAYOUT_KITCHEN
        )
        lines = kitchen.splitlines()
        self.assertTrue(all(line.strip() for line in lines), msg=repr(kitchen))
        # En-tête + 1 article + séparateurs ≈ 5 lignes max pour 1 produit.
        self.assertLessEqual(len(lines), 6, msg=repr(kitchen))


if __name__ == "__main__":
    unittest.main()
