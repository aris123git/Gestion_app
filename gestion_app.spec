# -*- mode: python ; coding: utf-8 -*-
"""Spécification PyInstaller — bundle Windows **onedir** allégé.

Sans ``collect_all(PySide6)`` (WebEngine, QML, Multimedia… → +150–200 Mo inutiles).
On n'embarque que Core/Gui/Widgets + plugins nécessaires (platforms, images).

Usage :
    pyinstaller gestion_app.spec
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

# Modules UI critiques : forcer l'inclusion même si l'analyse rate un import.
_CRITICAL_UI = [
    "app.ui.app",
    "app.ui.main_window",
    "app.ui.login_dialog",
    "app.ui.activation_dialog",
    "app.ui.setup_wizard",
    "app.ui.product_choice_dialog",
    "app.ui.pages.maquis_inventaire_page",
    "app.ui.widgets.maquis_period_bar",
    "app.ui.dialogs.maquis_payment_dialog",
    "app.ui.state",
    "app.ui.theme",
]

# Modules Qt inutilisés — exclus pour réduire la taille drastiquement.
_QT_EXCLUDES = [
    "PySide6.QtWebEngine",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtWebView",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.QtQmlModels",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSerialBus",
    "PySide6.QtRemoteObjects",
    "PySide6.QtTextToSpeech",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtHelp",
    "PySide6.QtTest",
    "PySide6.QtHttpServer",
    "PySide6.QtSpatialAudio",
    "PySide6.QtStateMachine",
]


def _qt_plugin_datas() -> list[tuple[str, str]]:
    """Plugins Qt minimaux (pas multimedia / qml / webengine)."""
    try:
        import PySide6
    except ImportError:
        return []
    root = Path(PySide6.__file__).parent
    candidates = [root / "Qt" / "plugins", root / "plugins"]
    plugins_root = next((p for p in candidates if p.is_dir()), None)
    if plugins_root is None:
        return []
    wanted = (
        "platforms",
        "imageformats",
        "iconengines",
        "styles",
        "platforminputcontexts",
        "generic",
    )
    datas: list[tuple[str, str]] = []
    for name in wanted:
        src = plugins_root / name
        if src.is_dir():
            # Dest alignée avec pyi_rth_pyside6.py → PySide6/Qt/plugins/...
            datas.append((str(src), f"PySide6/Qt/plugins/{name}"))
    # Traductions Qt FR (messages boîtes de dialogue natives) — optionnel / léger
    for tr_root in (root / "Qt" / "translations", root / "translations"):
        if not tr_root.is_dir():
            continue
        for pattern in ("qtbase_fr.qm", "qt_fr.qm"):
            qm = tr_root / pattern
            if qm.is_file():
                datas.append((str(qm), "PySide6/Qt/translations"))
        break
    return datas


hidden_imports = sorted(
    set(
        collect_submodules("app")
        + collect_submodules("escpos")
        + _CRITICAL_UI
        + [
            "PySide6.QtCore",
            "PySide6.QtGui",
            "PySide6.QtWidgets",
            "PySide6.QtNetwork",
            "PySide6.QtPrintSupport",
            "reportlab.graphics.barcode",
            "win32print",
            "win32ui",
        ]
    )
)

block_cipher = None

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("app/assets/shop_logos", "app/assets/shop_logos"),
    ]
    + _qt_plugin_datas(),
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["pyi_rth_pyside6.py"],
    excludes=["tkinter", "pytest", *_QT_EXCLUDES],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    # Modules en fichiers → un antivirus qui bloque un fichier n'efface pas tout.
    noarchive=True,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

_icon = "app/assets/icon.ico" if Path("app/assets/icon.ico").is_file() else None

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
    icon=_icon,
)

exe_console = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GestionCommerciale_console",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)

coll = COLLECT(
    exe,
    exe_console,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GestionCommerciale",
)
