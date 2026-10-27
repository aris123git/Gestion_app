"""Test : Entrée sur un client inconnu ouvre la fenêtre de création."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

_DATA_DIR = tempfile.mkdtemp(prefix="gestion_clientsearch_")
os.environ["GESTION_DATA_DIR"] = _DATA_DIR
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import config  # noqa: E402
from app.controllers.client_controller import ClientController  # noqa: E402
from app.database.connection import engine, init_database  # noqa: E402
from app.database.seed import seed_all  # noqa: E402
from app.ui.dialogs.contact_dialog import ContactDialog  # noqa: E402
from app.ui.widgets.client_search import ClientSearchField  # noqa: E402


class ClientSearchCreateTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        init_database()
        seed_all()

    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        shutil.rmtree(config.DATA_DIR, ignore_errors=True)

    def _run(self, typed: str):
        seen = {}

        def fake_exec(dialog):
            seen["name"], seen["phone"] = dialog.name.text(), dialog.phone.text()
            dialog.data = {"name": dialog.name.text() or "Nouveau", "phone": dialog.phone.text(), "phone2": "", "address": "", "email": "", "notes": ""}
            return True

        original = ContactDialog.exec
        ContactDialog.exec = fake_exec
        try:
            field = ClientSearchField()
            picked = []
            field.client_selected.connect(picked.append)
            field.input.setText(typed)
            field.input.returnPressed.emit()
        finally:
            ContactDialog.exec = original
        return field, seen, picked

    def test_unknown_name_prefills_name(self) -> None:
        field, seen, picked = self._run("Moussa Traoré")
        self.assertEqual(seen["name"], "Moussa Traoré")
        self.assertIsNotNone(field.client_id)
        self.assertEqual(picked[-1], field.client_id)

    def test_unknown_number_prefills_phone(self) -> None:
        field, seen, _picked = self._run("70 12 34 56")
        self.assertEqual(seen["phone"], "70123456")
        self.assertIsNotNone(field.client_id)

    def test_existing_client_does_not_open_dialog(self) -> None:
        ClientController.create({"name": "Awa Konaté", "phone": "76000000"})
        field, seen, _picked = self._run("Awa")
        self.assertEqual(seen, {})
        self.assertIsNotNone(field.client_id)


if __name__ == "__main__":
    unittest.main()
