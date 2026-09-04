"""Tests de la bibliothèque de designs de tickets."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
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
from app.printers.ticket.data import (  # noqa: E402
    TicketData,
    TicketLineItem,
    TicketPaymentLine,
    sample_ticket_data,
)
from app.printers.ticket.options import TicketOptions  # noqa: E402
from app.printers.ticket.registry import (  # noqa: E402
    CLIENT_DESIGNS,
    KITCHEN_DESIGNS,
    get_design,
    list_designs,
    resolve_client_design_id,
    resolve_kitchen_design_id,
)
from app.printers.ticket.renderer import (  # noqa: E402
    render_ticket,
    render_ticket_preview,
    render_ticket_text_from_data,
)
from app.printers.ticket.styled import lines_to_text  # noqa: E402


def _sale(**overrides):
    item = SimpleNamespace(
        product_name="Jus d'orange",
        quantity=2,
        unit_price=500,
        line_total=1000,
    )
    base = dict(
        ticket_number="T-TEST-1",
        date=datetime(2026, 9, 1, 14, 30),
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
    base.update(overrides)
    return SimpleNamespace(**base)


def _shop():
    return SimpleNamespace(
        name="Boutique Test",
        address="1 rue A",
        phone="0102030405",
        currency="FCFA",
        logo_path="",
        ticket_footer="Merci",
    )


class TicketDesignLibraryTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.mkdtemp(prefix="ticket_designs_")
        os.environ["GESTION_DATA_DIR"] = cls._tmpdir
        from app.database.connection import init_database
        from app.database.seed import seed_all

        init_database()
        seed_all()

    def test_all_designs_registered(self) -> None:
        client_ids = {d.id for d in CLIENT_DESIGNS}
        kitchen_ids = {d.id for d in KITCHEN_DESIGNS}
        self.assertEqual(
            client_ids,
            {
                "classic",
                "modern",
                "compact",
                "elegant",
                "restaurant",
                "minimal",
                "bold",
                "terminal",
                "facture",
            },
        )
        self.assertEqual(kitchen_ids, {"serveur", "cuisine", "cuisine_compact"})
        self.assertEqual(len(list_designs()), 12)

    def test_each_design_renders_58_and_80(self) -> None:
        data = sample_ticket_data()
        opts = TicketOptions()
        for design in list_designs():
            role = "kitchen" if design.category == "kitchen" else "client"
            for paper, width in (("58mm", 32), ("80mm", 48)):
                lines = render_ticket(
                    data, design_id=design.id, role=role, options=opts, paper=paper
                )
                text = lines_to_text(lines, width)
                self.assertTrue(text.strip(), msg=design.id)
                for line in text.splitlines():
                    self.assertLessEqual(
                        len(line),
                        width + 2,
                        msg=f"{design.id} {paper}: {line!r}",
                    )

    def test_kitchen_designs_have_no_prices(self) -> None:
        data = sample_ticket_data()
        for design in KITCHEN_DESIGNS:
            text = render_ticket_text_from_data(
                data, design_id=design.id, role="kitchen", paper="80mm"
            )
            self.assertNotIn("FCFA", text)
            self.assertNotIn("TOTAL", text.upper().replace("COMMANDE", ""))
            self.assertNotIn("Espèces", text)
            self.assertNotIn("1 000", text)  # montants absents
            self.assertIn("CAFÉ", text.upper())

    def test_serveur_and_cuisine_markers(self) -> None:
        data = sample_ticket_data()
        serveur = render_ticket_text_from_data(
            data, design_id="serveur", role="kitchen", paper="80mm"
        )
        cuisine = render_ticket_text_from_data(
            data, design_id="cuisine", role="kitchen", paper="80mm"
        )
        self.assertIn("A SERVIR", serveur)
        self.assertIn("COMMANDE", cuisine)
        self.assertNotIn("FCFA", serveur)
        self.assertNotIn("FCFA", cuisine)

    def test_hide_zero_change_and_absent_discount(self) -> None:
        data = sample_ticket_data()
        opts = TicketOptions(hide_zero_change=True, show_change=True, show_discount=True)
        text = render_ticket_text_from_data(
            data, design_id="classic", options=opts, paper="80mm"
        )
        self.assertNotIn("Monnaie", text)
        self.assertNotIn("Remise", text)

    def test_show_discount_when_present(self) -> None:
        data = sample_ticket_data()
        data.discount = 100
        data.total = 1200
        opts = TicketOptions(show_discount=True, show_subtotal=True)
        text = render_ticket_text_from_data(
            data, design_id="terminal", options=opts, paper="80mm"
        )
        self.assertIn("Remise", text)

    def test_long_product_name_and_many_items(self) -> None:
        long_name = "Produit avec un nom extrêmement long pour tester le wrapping thermique"
        items = [
            TicketLineItem(long_name, 1, 999999, 999999),
            *[TicketLineItem(f"Article {i}", i + 1, 100, 100 * (i + 1)) for i in range(12)],
        ]
        data = sample_ticket_data()
        data.items = items
        data.total = sum(i.line_total for i in items)
        for paper, width in (("58mm", 32), ("80mm", 48)):
            text = render_ticket_text_from_data(
                data, design_id="classic", paper=paper
            )
            for line in text.splitlines():
                self.assertLessEqual(len(line), width + 2, msg=repr(line))

    def test_preview_matches_design(self) -> None:
        for design in CLIENT_DESIGNS[:3]:
            preview = render_ticket_preview(design.id, paper="80mm")
            self.assertTrue(preview.strip())

    def test_legacy_layout_aliases(self) -> None:
        sale = _sale()
        shop = _shop()
        classic = render_ticket_text(
            sale, shop, paper="80mm", layout=TICKET_LAYOUT_CLASSIC
        )
        compact = render_ticket_text(
            sale, shop, paper="80mm", layout=TICKET_LAYOUT_COMPACT
        )
        table = render_ticket_text(
            sale, shop, paper="80mm", layout=TICKET_LAYOUT_TABLE
        )
        kitchen = render_ticket_text(
            sale, shop, paper="80mm", layout=TICKET_LAYOUT_KITCHEN
        )
        self.assertIn("Jus", classic)
        self.assertIn("TOTAL", classic)
        self.assertIn("2x", compact.lower().replace(" × ", "x").replace("×", "x") or compact)
        # table → terminal
        self.assertTrue("TICKET" in table or "Jus" in table or "JUS" in table.upper())
        self.assertIn("A SERVIR", kitchen)
        self.assertNotIn("FCFA", kitchen)

    def test_settings_persistence_design_ids(self) -> None:
        from app.services import settings_service

        settings_service.set_setting("ticket_client_design", "modern")
        settings_service.set_setting("ticket_kitchen_design", "cuisine")
        self.assertEqual(resolve_client_design_id(), "modern")
        self.assertEqual(resolve_kitchen_design_id(), "cuisine")
        settings_service.set_setting("ticket_client_design", "classic")
        settings_service.set_setting("ticket_kitchen_design", "serveur")

    def test_legacy_ticket_layout_migration(self) -> None:
        from app.services import settings_service

        settings_service.set_setting("ticket_client_design", "")
        settings_service.set_setting("ticket_layout", "table")
        self.assertEqual(resolve_client_design_id(), "terminal")
        settings_service.set_setting("ticket_layout", "kitchen")
        # client design fallback when empty client key + kitchen legacy
        # → mapped serveur is kitchen category, so client falls to classic
        self.assertEqual(resolve_client_design_id(), "classic")
        settings_service.set_setting("ticket_layout", "classic")

    def test_get_design_unknown_falls_back(self) -> None:
        self.assertEqual(get_design("unknown-xyz").id, "classic")

    def test_options_toggle_header(self) -> None:
        data = sample_ticket_data()
        opts = TicketOptions(
            show_shop_name=False,
            show_phone=False,
            show_address=False,
            show_cashier=False,
            show_footer=False,
        )
        text = render_ticket_text_from_data(
            data, design_id="classic", options=opts, paper="80mm"
        )
        self.assertNotIn("Café du Port", text)
        self.assertNotIn("0600000000", text)
        self.assertNotIn("12 rue X", text)

    def test_money_alignment_right(self) -> None:
        data = sample_ticket_data()
        text = render_ticket_text_from_data(
            data, design_id="classic", paper="80mm"
        )
        # Les montants doivent apparaître vers la droite de la ligne.
        for line in text.splitlines():
            if "FCFA" in line and "TOTAL" not in line and "Tel" not in line:
                self.assertTrue(
                    line.rstrip().endswith("FCFA") or "FCFA" in line[-20:],
                    msg=repr(line),
                )

    def test_facture_tableau_structure(self) -> None:
        data = sample_ticket_data()
        data.shop_email = "contact@cafe.port"
        data.shop_fax = "50 30 13 78"
        for paper in ("58mm", "80mm"):
            text = render_ticket_text_from_data(
                data, design_id="facture", paper=paper
            )
            self.assertIn("COMPTANT", text)
            self.assertIn("N° Facture", text)
            self.assertIn("Client", text)
            self.assertTrue("Designation" in text or "Article" in text)
            self.assertIn("Qte", text)
            self.assertIn("Prix", text)
            self.assertIn("Montant", text)
            self.assertIn("TOTAL", text)
            self.assertIn("Arrêtée la présente facture", text)
            self.assertIn("Tel :", text)
            self.assertIn("Fax :", text)
            # Tableau cadré avec colonnes (photo).
            self.assertIn("┌", text)
            self.assertIn("┬", text)
            self.assertIn("│", text)
            self.assertIn("└", text)
            # Cadre montant en lettres (coins droits = traits continus CP850).
            self.assertIn("┌", text)
            # TOTAL souligné (trait sous le montant, pas cadre total).
            self.assertIn("─", text)
            self.assertIn("mille", text.lower())
            # Traits verticaux alignés sur toutes les lignes du tableau.
            table_rows = [
                ln for ln in text.splitlines() if ln.startswith("│") or ln.startswith("┌") or ln.startswith("├") or ln.startswith("└")
            ]
            # Exclure le cadre montant en lettres (une seule paire │ latéraux).
            grid = [ln for ln in table_rows if ln.count("│") >= 4 or ln.count("┬") or ln.count("┼") or ln.count("┴")]
            self.assertGreaterEqual(len(grid), 4)
            positions = None
            for ln in grid:
                pos = tuple(i for i, c in enumerate(ln) if c in "│┌┐└┘├┤┬┴┼")
                if positions is None:
                    positions = pos
                else:
                    self.assertEqual(pos, positions, msg=repr(ln))
            width = 32 if paper == "58mm" else 48
            for line in text.splitlines():
                self.assertLessEqual(len(line), width + 2, msg=repr(line))

    def test_facture_header_name_left_address_right(self) -> None:
        data = sample_ticket_data()
        data.shop_name = "HARD SARL"
        data.shop_address = "Avenue de la République"
        data.shop_phone = "33 800 00 00"
        text = render_ticket_text_from_data(data, design_id="facture", paper="80mm")
        first = text.splitlines()[0]
        self.assertTrue(first.startswith("HARD SARL") or "HARD SARL" in first[:20])
        self.assertIn("Avenue", first or text.splitlines()[1])
        # Adresse pas uniquement sous le nom en pleine largeur gauche.
        self.assertIn("Tel :", text)

    def test_facture_bold_amount_lines(self) -> None:
        from app.printers.ticket.renderer import render_ticket
        from app.printers.ticket.options import TicketOptions

        data = sample_ticket_data()
        opts = TicketOptions(bold_prices=True, bold_total=True)
        styled = render_ticket(
            data, design_id="facture", options=opts, paper="80mm"
        )
        bold_texts = [s.text for s in styled if s.bold]
        self.assertTrue(any("TOTAL" in t for t in bold_texts))
        # Lignes du tableau (avec │) : jamais en gras — sinon traits discontinus.
        item_lines = [
            s for s in styled if ("Café" in s.text or "Croissant" in s.text) and "│" in s.text
        ]
        self.assertTrue(item_lines)
        self.assertTrue(all(not s.bold for s in item_lines))
        border_lines = [
            s for s in styled if s.text.startswith(("┌", "├", "└")) and s.text.count("─") > 5
        ]
        self.assertTrue(border_lines)
        self.assertTrue(all(not s.bold for s in border_lines))

    def test_kitchen_enable_disable_setting(self) -> None:
        from app.printers.ticket.options import (
            is_kitchen_ticket_enabled,
            set_kitchen_ticket_enabled,
        )

        set_kitchen_ticket_enabled(True)
        self.assertTrue(is_kitchen_ticket_enabled())
        set_kitchen_ticket_enabled(False)
        self.assertFalse(is_kitchen_ticket_enabled())
        set_kitchen_ticket_enabled(True)


class AmountWordsTestCase(unittest.TestCase):
    def test_basic_amounts(self) -> None:
        from app.utils.amount_words import amount_in_words, int_to_french_words

        self.assertEqual(int_to_french_words(0), "zéro")
        self.assertEqual(int_to_french_words(21), "vingt et un")
        self.assertEqual(int_to_french_words(80), "quatre-vingts")
        self.assertIn("mille", int_to_french_words(1300))
        self.assertIn("F CFA", amount_in_words(78000, "FCFA"))
        self.assertIn("soixante", amount_in_words(78, "FCFA").lower())


if __name__ == "__main__":
    unittest.main()
