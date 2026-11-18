import os, tempfile, unittest
from unittest.mock import patch
os.environ.setdefault("GESTION_DATA_DIR", tempfile.mkdtemp())
os.environ["NEXAPOS_SKIP_ACTIVATION"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"


class ExpensesPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from app.database.connection import init_database
        from app.database.seed import seed_all
        init_database()
        seed_all()

    def test_filter_and_edit(self):
        from app import config
        from app.controllers.expense_controller import ExpenseController as E
        from app.ui.pages.expenses_page import ExpensesPage
        from app.ui.state import AppState
        c1, c2 = config.EXPENSE_CATEGORIES[0], config.EXPENSE_CATEGORIES[1]
        E.create({"category": c1, "label": "AAA", "amount": 1000}, user_id=1)
        E.create({"category": c2, "label": "BBB", "amount": 3000}, user_id=1)
        st = AppState()
        st.can = lambda p: True
        pu = patch.object(AppState, 'user_id', new=property(lambda s: 1))
        pu.start()
        self.addCleanup(pu.stop)
        pg = ExpensesPage(st)
        pg.refresh()
        self.assertEqual(pg.table.rowCount(), 2)
        self.assertIn("4", pg.k_total.text().replace(" ", "").replace(" ", ""))
        pg._set_category(c2)
        self.assertEqual(pg.table.rowCount(), 1)
        pg._set_category(None)
        pg.search.setText("aaa")
        self.assertEqual(pg.table.rowCount(), 1)
        pg.search.setText("")
        pg.table.setCurrentCell(0, 0)
        eid = pg._ids[0]
        with patch("app.ui.pages.expenses_page.warn", side_effect=lambda p, m: self.fail(m)), patch("app.ui.pages.expenses_page.ExpenseDialog") as D:
            D.return_value.exec.return_value = True
            D.return_value.values.return_value = {"category": c1, "label": "ZZZ", "amount": 500}
            pg._edit()
        self.assertTrue(any(e.id == eid and e.label == "ZZZ" for e in E.list()))


if __name__ == "__main__":
    unittest.main()
