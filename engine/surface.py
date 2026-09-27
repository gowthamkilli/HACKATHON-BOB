"""Shared-surface computation (§9, M6).

Lane tests (M9) may reference only symbols in the shared surface — the constraint that makes
one test file runnable unchanged on both `base` and `head`. Without it, the differential
comparison of §3/§4 is meaningless: a test touching a symbol that only exists on one side isn't
proving anything about the merge, it's proving the symbol exists.
"""
from __future__ import annotations

import ast
from pathlib import Path


def _public_functions(app_dir: Path) -> dict[str, str]:
    """qualname -> normalized signature string, for every public function/method under `app_dir`."""
    app_dir = Path(app_dir)
    result: dict[str, str] = {}
    if not app_dir.exists():
        return result

    for py_file in sorted(app_dir.rglob("*.py")):
        module = "app." + str(py_file.relative_to(app_dir)).replace("/", ".").replace("\\", ".")[:-3]
        module = module.removesuffix(".__init__")
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        def visit(node: ast.AST, scope: list[str]) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not child.name.startswith("_"):
                        qualname = ".".join([module] + scope + [child.name])
                        result[qualname] = ast.unparse(child.args)
                    visit(child, scope + [child.name])
                elif isinstance(child, ast.ClassDef):
                    visit(child, scope + [child.name])

        visit(tree, [])

    return result


def shared_surface(base_app_dir: Path, head_app_dir: Path) -> list[str]:
    base_symbols = _public_functions(base_app_dir)
    head_symbols = _public_functions(head_app_dir)
    shared = [
        qn for qn, sig in base_symbols.items()
        if qn in head_symbols and head_symbols[qn] == sig
    ]
    return sorted(shared)
