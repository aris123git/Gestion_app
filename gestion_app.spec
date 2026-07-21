# -*- mode: python ; coding: utf-8 -*-
"""Spécification PyInstaller pour générer l'exécutable Windows.

Génère un exécutable autonome (un seul fichier) nommé ``GestionCommerciale``.

Usage :
    pyinstaller gestion_app.spec

Les données de l'application (base SQLite, sauvegardes, tickets) sont créées au
runtime dans le dossier de données de l'utilisateur (``%APPDATA%`` sur Windows),
elles ne sont donc pas embarquées dans l'exécutable.
"""

from PyInstaller.utils.hooks import collect_submodules

hidden_imports = (
    collect_submodules("app")
    + collect_submodules("escpos")
    + ["reportlab.graphics.barcode", "win32print", "win32ui"]
)

block_cipher = None


a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="GestionCommerciale",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Application graphique : pas de console.
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="app/assets/icon.ico" if __import__("os").path.exists("app/assets/icon.ico") else None,
)
