# -*- mode: python ; coding: utf-8 -*-
"""Spécification PyInstaller pour générer l'exécutable Windows.

Mode **onedir** (dossier ``dist/GestionCommerciale/``) : plus robuste que
onefile face aux antivirus qui altèrent l'extraction dans ``%TEMP%``
(symptôme fréquent : ``ModuleNotFoundError: app.ui.main_window``).

Usage :
    pyinstaller gestion_app.spec

Les données métier (SQLite, sauvegardes, tickets) restent dans ``%APPDATA%``.
"""

from PyInstaller.utils.hooks import collect_submodules

# Modules UI critiques : forcer l'inclusion même si l'analyse rate un import.
_CRITICAL_UI = [
    "app.ui.app",
    "app.ui.main_window",
    "app.ui.login_dialog",
    "app.ui.activation_dialog",
    "app.ui.setup_wizard",
    "app.ui.product_choice_dialog",
    "app.ui.state",
    "app.ui.theme",
]

hidden_imports = sorted(
    set(
        collect_submodules("app")
        + collect_submodules("escpos")
        + _CRITICAL_UI
        + ["reportlab.graphics.barcode", "win32print", "win32ui"]
    )
)

block_cipher = None


a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("app/assets/shop_logos", "app/assets/shop_logos"),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    # Modules en fichiers (pas dans un seul PYZ) → un antivirus qui bloque
    # un fichier n'efface pas tout le package d'un coup.
    noarchive=True,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GestionCommerciale",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="app/assets/icon.ico" if __import__("os").path.exists("app/assets/icon.ico") else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GestionCommerciale",
)
