"""Dialogues restants repérés après l'inventaire initial (Caisse Maquis :
accessoires, pavé quantité ; BTP : enlèvements) — nouvel habillage visuel
(bandeaux d'en-tête) — vérifie que la logique de ces dialogues reste intacte."""
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NEXAPOS_SKIP_ACTIVATION", "1")


def _has_banner(widget) -> bool:
    from PySide6.QtWidgets import QWidget
    return any(w.objectName() == "DialogHeaderBanner" for w in widget.findChildren(QWidget))


class AccessoryPickerDialogRedesignTest(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def test_header_banner_and_total_computation_unchanged(self):
        from app.ui.dialogs.accessory_picker_dialog import AccessoryPickerDialog

        dialog = AccessoryPickerDialog("Poisson braisé", 2000, [{"name": "Attiéké", "price": 300}], "FCFA")
        self.assertTrue(_has_banner(dialog))
        dialog._checks[0][0].setChecked(True)
        self.assertIn("2 300", dialog.total_label.text().replace("\xa0", " "))


class QuantityPadDialogRedesignTest(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def test_header_banner_and_digits_unchanged(self):
        from app.ui.dialogs.quantity_pad_dialog import QuantityPadDialog

        dialog = QuantityPadDialog("Riz", initial=2.0)
        self.assertTrue(_has_banner(dialog))
        dialog._digit("5")
        self.assertEqual(dialog.display.text(), "25")


class _DBTestCase(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="gestion_pickups_dialogs_")
        os.environ["GESTION_DATA_DIR"] = self._dir
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        from app.database.connection import engine, init_database
        from app.database.seed import seed_all
        engine.dispose()
        init_database()
        seed_all()

    def tearDown(self):
        from app.database.connection import engine
        engine.dispose()
        shutil.rmtree(self._dir, ignore_errors=True)


class PickupsDialogsRedesignTest(_DBTestCase):
    def test_header_banners_present_on_all_pickup_dialogs(self):
        from app.ui.dialogs import pickups_dialog as pd
        from app.ui.state import AppState

        state = AppState()
        state.auth.login("admin", "admin")

        edit = pd.PickupEditDialog()
        self.assertTrue(_has_banner(edit))

        validate = pd.ValidatePickupDialog(total=1000, tax=0)
        self.assertTrue(_has_banner(validate))

        close = pd.ClosePickupDialog(None, [])
        self.assertTrue(_has_banner(close))

        listing = pd.PickupsDialog(state)
        self.assertTrue(_has_banner(listing))


if __name__ == "__main__":
    unittest.main()
