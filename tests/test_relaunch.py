"""Relance automatique : commande construite correctement, sans lancer de vrai processus."""
import os, sys, unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from app.ui import relaunch  # noqa: E402


class RelaunchTests(unittest.TestCase):
    def test_command_dev_and_frozen(self):
        with mock.patch.object(sys, "argv", ["main.py", "--x"]):
            self.assertEqual(relaunch.relaunch_command(), (sys.executable, ["main.py", "--x"]))
            with mock.patch.object(sys, "frozen", True, create=True):
                self.assertEqual(relaunch.relaunch_command(), (sys.executable, ["--x"]))

    def test_relaunch_starts_process_then_quits(self):
        app = QApplication.instance() or QApplication([])
        with mock.patch.object(relaunch.QProcess, "startDetached", return_value=True) as start, \
                mock.patch.object(app, "quit") as quit_:
            relaunch.relaunch_application()
        start.assert_called_once()
        quit_.assert_called_once()

    def test_failure_still_quits(self):
        app = QApplication.instance() or QApplication([])
        with mock.patch.object(relaunch.QProcess, "startDetached", return_value=False), mock.patch.object(app, "quit") as quit_:
            relaunch.relaunch_application()
        quit_.assert_called_once()


if __name__ == "__main__":
    unittest.main()
