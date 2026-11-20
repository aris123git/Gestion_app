"""Mémorise, sur cet ordinateur, quels groupes du menu de navigation sont ouverts."""
from __future__ import annotations

import json
from pathlib import Path

from app import config


def _path() -> Path:
    return config.DATA_DIR / "nav_state.json"


def get_open_groups() -> set[str]:
    p = _path()
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text(encoding="utf-8")).get("open_groups", []))
    except Exception:
        return set()


def set_open_groups(groups: set[str]) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _path().write_text(json.dumps({"open_groups": sorted(groups)}), encoding="utf-8")
    except OSError:
        pass
