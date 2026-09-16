"""Vérifie que l'EXE PyInstaller (onefile) embarque les modules UI critiques."""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED = (
    "app.ui.app",
    "app.ui.main_window",
    "app.ui.login_dialog",
    "app.ui.pages.maquis_inventaire_page",
    "app.main",
)


def _find_exe(path: Path) -> Path:
    if path.is_file():
        return path
    for name in (
        "GestionCommerciale.exe",
        "GestionCommerciale",
        "GestionCommerciale_console.exe",
    ):
        candidate = path / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"EXE introuvable sous {path}")


def _archive_names(exe: Path) -> set[str]:
    try:
        from PyInstaller.archive.readers import CArchiveReader
    except ImportError:
        return set()
    archive = CArchiveReader(str(exe))
    return {str(name) for name in archive.toc}


def _pyz_modules(exe: Path) -> set[str]:
    """Lit le PYZ embarqué dans l'EXE onefile."""
    try:
        from PyInstaller.archive.readers import CArchiveReader
        from PyInstaller.loader.pyimod01_archive import ZlibArchiveReader
    except ImportError:
        return set()

    archive = CArchiveReader(str(exe))
    pyz_name = next(
        (name for name in archive.toc if str(name).lower().endswith(".pyz")),
        None,
    )
    if not pyz_name:
        return set()
    pyz_path = exe.with_suffix(".pyz")
    pyz_path.write_bytes(archive.extract(pyz_name))
    try:
        zlib_archive = ZlibArchiveReader(str(pyz_path))
        return set(zlib_archive.toc.keys())
    finally:
        pyz_path.unlink(missing_ok=True)


def _qt_platform_in_archive(exe: Path) -> bool:
    """Plugins Qt embarqués dans l'archive onefile."""
    names = _archive_names(exe)
    if not names:
        return True
    lowered = {n.replace("\\", "/").lower() for n in names}
    return any(
        "plugins/platforms/qwindows" in n or n.endswith("qwindows.dll")
        for n in lowered
    )


def main() -> int:
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
    else:
        target = Path("dist/GestionCommerciale.exe")
        if not target.is_file():
            target = Path("dist")

    try:
        exe = _find_exe(target)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    try:
        from PyInstaller.archive.readers import CArchiveReader  # noqa: F401
    except ImportError:
        print(f"OK — EXE présent ({exe}), vérif PYZ ignorée (PyInstaller absent)")
        return 0

    pyz_hits = _pyz_modules(exe)
    if not pyz_hits:
        print("Aucun PYZ dans l'EXE — bundle invalide ?", file=sys.stderr)
        return 1

    missing = [name for name in REQUIRED if name not in pyz_hits]
    if missing:
        print("Modules manquants dans le PYZ :", ", ".join(missing), file=sys.stderr)
        print(f"  trouvés: {[m for m in REQUIRED if m in pyz_hits]}", file=sys.stderr)
        return 1

    if not _qt_platform_in_archive(exe):
        print(
            "Plugin Qt qwindows introuvable dans l'archive onefile.",
            file=sys.stderr,
        )
        return 1

    console_exe = exe.parent / "GestionCommerciale_console.exe"
    if not console_exe.is_file() and not (exe.parent / "GestionCommerciale_console").is_file():
        print("Avertissement : GestionCommerciale_console.exe absent", file=sys.stderr)

    print(f"OK — modules critiques présents dans {exe.name} (onefile)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
