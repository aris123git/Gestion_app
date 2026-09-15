"""Vérifie que l'EXE PyInstaller embarque les modules UI critiques."""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED = (
    "app.ui.app",
    "app.ui.main_window",
    "app.ui.login_dialog",
    "app.main",
)


def main() -> int:
    exe = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/GestionCommerciale.exe")
    if not exe.is_file():
        print(f"EXE introuvable : {exe}", file=sys.stderr)
        return 1

    from PyInstaller.archive.readers import CArchiveReader
    from PyInstaller.loader.pyimod01_archive import ZlibArchiveReader

    archive = CArchiveReader(str(exe))
    pyz_name = next(
        (name for name in archive.toc if str(name).lower().endswith(".pyz")),
        None,
    )
    if not pyz_name:
        print("Archive PYZ introuvable dans l'EXE.", file=sys.stderr)
        return 1

    pyz_path = exe.with_suffix(".pyz")
    pyz_path.write_bytes(archive.extract(pyz_name))
    try:
        zlib_archive = ZlibArchiveReader(str(pyz_path))
        keys = set(zlib_archive.toc.keys())
    finally:
        pyz_path.unlink(missing_ok=True)

    missing = [name for name in REQUIRED if name not in keys]
    if missing:
        print("Modules manquants dans l'EXE :", ", ".join(missing), file=sys.stderr)
        return 1

    print(f"OK — modules critiques présents dans {exe.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
