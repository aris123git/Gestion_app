"""Tests profils imprimante + encodage ESC/POS (accents FR)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

_DATA_DIR = tempfile.mkdtemp(prefix="nexapos_enc_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")

from app import config  # noqa: E402
from app.database.connection import init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.printers.escpos_encoder import (  # noqa: E402
    ACCENT_TEST_SAMPLE,
    build_escpos_document,
    encode_text,
    prepare_text,
)
from app.printers.printer_profile import (  # noqa: E402
    DEFAULT_PROFILE_ID_58,
    DEFAULT_PROFILE_ID_80,
    PRINTER_PROFILES,
    get_profile,
    resolve_printer_profile,
    save_printer_profile_id,
)
from app.printers.ticket.data import sample_ticket_data  # noqa: E402
from app.printers.ticket.renderer import paper_width, render_ticket  # noqa: E402
from app.printers.ticket.styled import StyledLine, lines_to_escpos_bytes  # noqa: E402
from app.services import settings_service  # noqa: E402


def setUpModule() -> None:
    init_database()
    seed_all()


def tearDownModule() -> None:
    shutil.rmtree(config.DATA_DIR, ignore_errors=True)


class PrinterProfileTestCase(unittest.TestCase):
    def test_profiles_cover_58_and_80(self):
        papers = {p.paper_width for p in PRINTER_PROFILES.values()}
        self.assertIn("58mm", papers)
        self.assertIn("80mm", papers)

    def test_default_resolve_by_paper(self):
        settings_service.set_setting("printer_profile_id", "")
        settings_service.set_setting("ticket_format", "58mm")
        p58 = resolve_printer_profile(paper="58mm")
        self.assertEqual(p58.characters_per_line, 32)
        self.assertEqual(p58.encoding, "cp850")
        p80 = resolve_printer_profile(paper="80mm")
        self.assertGreaterEqual(p80.characters_per_line, 42)
        self.assertEqual(p80.id, DEFAULT_PROFILE_ID_80)

    def test_save_profile_aligns_paper(self):
        save_printer_profile_id(DEFAULT_PROFILE_ID_58)
        self.assertEqual(settings_service.get_setting("ticket_format"), "58mm")
        save_printer_profile_id(DEFAULT_PROFILE_ID_80)
        self.assertEqual(settings_service.get_setting("ticket_format"), "80mm")


class EscposEncodingTestCase(unittest.TestCase):
    def test_cafe_cp850_not_utf8(self):
        profile = get_profile("generic_80_cp850")
        raw = encode_text("Café", profile)
        self.assertNotIn(b"\xc3\xa9", raw)
        self.assertEqual(raw, bytes([0x43, 0x61, 0x66, 0x82]))

    def test_french_accents_roundtrip_cp850(self):
        profile = get_profile("generic_80_cp850")
        sample = "éèêëàâäùûüîïôöçÉÀ"
        decoded = encode_text(sample, profile).decode("cp850")
        for ch in sample:
            self.assertIn(ch, decoded, msg=f"manque {ch!r}")

    def test_oe_transliterated(self):
        profile = get_profile("generic_80_cp850")
        self.assertEqual(prepare_text("œuvre", profile), "oeuvre")
        self.assertEqual(encode_text("œuvre", profile).decode("cp850"), "oeuvre")

    def test_rounded_corners_mapped(self):
        profile = get_profile("generic_80_cp850")
        self.assertEqual(prepare_text("╭─╮", profile), "┌─┐")

    def test_document_sets_codepage_and_encodes(self):
        profile = get_profile("generic_80_cp850")
        out = build_escpos_document(
            "Café école\n",
            profile,
            feed_lines=0,
            cut_mode="none",
            include_logo=False,
        )
        self.assertIn(b"\x1b\x74\x02", out)
        self.assertNotIn(b"\xc3\xa9", out)
        self.assertIn(bytes([0x82]), out)

    def test_styled_lines_use_profile(self):
        profile = get_profile("generic_58_cp850")
        lines = [StyledLine("Crème brûlée", bold=True, align="center")]
        out = lines_to_escpos_bytes(
            lines,
            feed_lines=0,
            cut_mode="none",
            include_logo=False,
            paper="58mm",
            profile=profile,
        )
        self.assertIn(b"\x1b\x74\x02", out)
        self.assertNotIn(b"\xc3\xa9", out)

    def test_accent_sample_encodes(self):
        profile = get_profile("generic_80_cp850")
        out = build_escpos_document(
            ACCENT_TEST_SAMPLE,
            profile,
            feed_lines=1,
            cut_mode="none",
            include_logo=False,
        )
        self.assertGreater(len(out), 40)
        self.assertNotIn(b"\xc3\xa9", out)

    def test_paper_width_follows_profile(self):
        save_printer_profile_id("generic_80_narrow_cp850")
        self.assertEqual(paper_width("80mm"), 42)
        save_printer_profile_id(DEFAULT_PROFILE_ID_58)
        self.assertEqual(paper_width("58mm"), 32)

    def test_facture_renders_at_32_and_48(self):
        data = sample_ticket_data()
        for w in (32, 42, 48):
            lines = render_ticket(
                data, design_id="facture", role="client", paper="80mm", width=w
            )
            self.assertTrue(lines)
            text_lines = [ln.text or "" for ln in lines]
            for text in text_lines:
                self.assertLessEqual(
                    len(text),
                    w + 2,
                    msg=f"ligne trop longue à width={w}: {text!r}",
                )


if __name__ == "__main__":
    unittest.main()
