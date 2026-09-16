"""Vérifie que le bundle PyInstaller embarque les modules UI critiques."""

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
    if path.is_file() and path.suffix.lower() == ".exe":
        return path
    candidate = path / "GestionCommerciale.exe"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(f"EXE introuvable sous {path}")


def _module_files_present(bundle_dir: Path) -> list[str]:
    """Cherche les .pyc / .py des modules requis (mode noarchive / onedir)."""
    found: list[str] = []
    search_roots = [bundle_dir, bundle_dir / "_internal"]
    for module in REQUIRED:
        parts = module.split(".")
        ok = False
        for root in search_roots:
            base = root.joinpath(*parts)
            for suffix in (".pyc", ".py", ".pyo"):
                if base.with_suffix(suffix).is_file():
                    ok = True
                    break
            # parfois app/ui/__pycache__/main_window.cpython-312.pyc
            cache = root.joinpath(*parts[:-1]) / "__pycache__"
            if cache.is_dir():
                stem = parts[-1]
                if any(cache.glob(f"{stem}*.pyc")):
                    ok = True
            if ok:
                break
        if ok:
            found.append(module)
    return found


def _pyz_modules(exe: Path) -> set[str]:
    """Lit le PYZ si présent. Sans PyInstaller installé → ensemble vide."""
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


def _qt_platform_plugin_ok(bundle_dir: Path) -> bool:
    """Vérifie que les plugins Qt (souvent oubliés) sont dans _internal."""
    for root in (bundle_dir / "_internal", bundle_dir):
        platforms = root / "PySide6" / "plugins" / "platforms"
        if not platforms.is_dir():
            continue
        for pattern in ("qwindows*.dll", "qxcb*.so", "libqxcb*.so"):
            if any(platforms.glob(pattern)):
                return True
    return False


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/GestionCommerciale")
    try:
        exe = _find_exe(target)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    bundle_dir = exe.parent
    file_hits = set(_module_files_present(bundle_dir))
    # Mode onedir + noarchive : les .pyc suffisent ; PYZ optionnel.
    pyz_hits: set[str] = set()
    missing_from_files = [name for name in REQUIRED if name not in file_hits]
    if missing_from_files:
        pyz_hits = _pyz_modules(exe)

    present = file_hits | {m for m in REQUIRED if m in pyz_hits}
    missing = [name for name in REQUIRED if name not in present]

    if missing:
        print("Modules manquants dans le bundle :", ", ".join(missing), file=sys.stderr)
        print(f"  fichiers trouvés: {sorted(file_hits)}", file=sys.stderr)
        print(f"  dans PYZ: {[m for m in REQUIRED if m in pyz_hits]}", file=sys.stderr)
        return 1

    if not _qt_platform_plugin_ok(bundle_dir):
        print(
            "Plugin Qt plateforme introuvable (PySide6/plugins/platforms). "
            "L'EXE Windows ne démarrera probablement pas.",
            file=sys.stderr,
        )
        return 1

    console_exe = bundle_dir / "GestionCommerciale_console.exe"
    if not console_exe.is_file():
        print("Avertissement : GestionCommerciale_console.exe absent", file=sys.stderr)

    print(f"OK — modules critiques présents dans {bundle_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
