#!/usr/bin/env python3
"""Enveloppe les littéraux UI visibles avec t(\"…\") pour l'i18n."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app" / "ui"

WRAP_FUNCS = {
    "QPushButton",
    "QLabel",
    "page_title",
    "section_title",
    "warn",
    "info",
    "error",
    "confirm",
}
WRAP_ATTRS = {
    "setWindowTitle",
    "setPlaceholderText",
    "setToolTip",
    "setAccessibleName",
    "setSuffix",
}
# Méthodes dont l'argument texte n'est pas toujours le 1er
# addItem(text) or addItem(text, data) — wrap arg0
# addTab(widget, text) — wrap arg1
# addRow(label, field) — wrap arg0 if str
# setHorizontalHeaderLabels([...]) — wrap each list elt


def _is_t_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "t"
    )


def _wrap(node: ast.AST) -> ast.AST:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if not node.value.strip():
            return node
        if _is_t_call(node):
            return node
        return ast.Call(func=ast.Name(id="t", ctx=ast.Load()), args=[node], keywords=[])
    return node


class I18nWrapper(ast.NodeTransformer):
    def __init__(self) -> None:
        self.changed = False
        self.need_import = False

    def visit_Call(self, node: ast.Call):
        self.generic_visit(node)
        func = node.func

        # QPushButton("x") / page_title("x") / warn(self, "x")
        if isinstance(func, ast.Name) and func.id in WRAP_FUNCS:
            if func.id in ("warn", "info", "error", "confirm"):
                # message often arg1 (after self/parent)
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    node.args[1] = _wrap(node.args[1])
                    self.changed = True
                    self.need_import = True
                if len(node.args) >= 3 and isinstance(node.args[2], ast.Constant):
                    node.args[2] = _wrap(node.args[2])
                    self.changed = True
                    self.need_import = True
                for kw in node.keywords:
                    if kw.arg in ("message", "title") and isinstance(
                        kw.value, ast.Constant
                    ):
                        kw.value = _wrap(kw.value)
                        self.changed = True
                        self.need_import = True
            else:
                if node.args and isinstance(node.args[0], ast.Constant):
                    node.args[0] = _wrap(node.args[0])
                    self.changed = True
                    self.need_import = True
            return node

        if isinstance(func, ast.Attribute) and func.attr in WRAP_ATTRS:
            if node.args and isinstance(node.args[0], ast.Constant):
                node.args[0] = _wrap(node.args[0])
                self.changed = True
                self.need_import = True
            return node

        if isinstance(func, ast.Attribute) and func.attr == "addItem":
            if node.args and isinstance(node.args[0], ast.Constant):
                node.args[0] = _wrap(node.args[0])
                self.changed = True
                self.need_import = True
            return node

        if isinstance(func, ast.Attribute) and func.attr == "addTab":
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                node.args[1] = _wrap(node.args[1])
                self.changed = True
                self.need_import = True
            return node

        if isinstance(func, ast.Attribute) and func.attr == "addRow":
            if node.args and isinstance(node.args[0], ast.Constant):
                node.args[0] = _wrap(node.args[0])
                self.changed = True
                self.need_import = True
            return node

        if isinstance(func, ast.Attribute) and func.attr == "setHorizontalHeaderLabels":
            if node.args and isinstance(node.args[0], ast.List):
                new_elts = []
                for elt in node.args[0].elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        new_elts.append(_wrap(elt))
                        self.changed = True
                        self.need_import = True
                    else:
                        new_elts.append(elt)
                node.args[0].elts = new_elts
            return node

        return node


def ensure_import(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "app.i18n":
            names = {a.name for a in node.names}
            if "t" in names:
                return False
            node.names.append(ast.alias(name="t", asname=None))
            return True
    # Insert after __future__ / docstring
    insert_at = 0
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            insert_at = i + 1
            continue
        if i == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            insert_at = 1
            continue
        break
    tree.body.insert(
        insert_at,
        ast.ImportFrom(module="app.i18n", names=[ast.alias(name="t", asname=None)], level=0),
    )
    return True


def process(path: Path) -> bool:
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        print("SKIP syntax", path)
        return False
    wrapper = I18nWrapper()
    tree = wrapper.visit(tree)
    if not wrapper.changed:
        return False
    if wrapper.need_import:
        ensure_import(tree)
    ast.fix_missing_locations(tree)
    new_src = ast.unparse(tree)
    path.write_text(new_src + "\n", encoding="utf-8")
    print("WRAPPED", path.relative_to(ROOT.parent.parent))
    return True


def main() -> None:
    count = 0
    for path in sorted(ROOT.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        if "responsive" in path.parts:
            continue
        if process(path):
            count += 1
    print(f"done files={count}")


if __name__ == "__main__":
    main()
