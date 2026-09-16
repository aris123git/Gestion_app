"""Runtime hook PyInstaller : DLL et plugins Qt (PySide6) sur Windows.

Sans cela, l'EXE ``console=False`` peut quitter immédiatement avec
« Could not load the Qt platform plugin windows » sans message visible.
"""

from __future__ import annotations

import os
import sys


def _prepend_path(directory: str) -> None:
    if not directory or not os.path.isdir(directory):
        return
    path = os.environ.get("PATH", "")
    if directory not in path.split(os.pathsep):
        os.environ["PATH"] = directory + os.pathsep + path
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(directory)
        except OSError:
            pass


if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    base = sys._MEIPASS
    _prepend_path(os.path.join(base, "PySide6"))
    plugins = os.path.join(base, "PySide6", "plugins")
    if os.path.isdir(plugins):
        os.environ.setdefault("QT_PLUGIN_PATH", plugins)
    platforms = os.path.join(plugins, "platforms")
    if os.path.isdir(platforms):
        os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", platforms)
