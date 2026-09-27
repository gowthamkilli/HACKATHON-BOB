"""AST call graph — computed structure the blast-radius agents judge, never traverse further.

Resolution is deliberately modest: within-module calls, plus cross-module calls through a
`from app import x` / `import app.x as x` alias table built per file. This is enough to find
"who calls the changed symbol, within 3 hops" for a codebase the size of `samples/orderworks`;
it does not attempt whole-program points-to analysis.
"""
from __future__ import annotations

import ast
from pathlib import Path


class _DefCollector(ast.NodeVisitor):
    def __init__(self, module: str):
        self.module = module
        self.scope: list[str] = []
        self.defs: dict[str, ast.AST] = {}  # qualname -> def node
        self.imports: dict[str, str] = {}  # local name -> module.attr it refers to

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            self.imports[local] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        for alias in node.names:
            local = alias.asname or alias.name
            self.imports[local] = f"{mod}.{alias.name}" if mod else alias.name

    def _qualname(self, name: str) -> str:
        parts = [self.module] + self.scope + [name]
        return ".".join(parts)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.defs[self._qualname(node.name)] = node
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


class _CallCollector(ast.NodeVisitor):
    def __init__(self):
        self.calls: list[str] = []  # dotted call target names, unresolved

    def visit_Call(self, node: ast.Call) -> None:
        target = self._dotted(node.func)
        if target:
            self.calls.append(target)
        self.generic_visit(node)

    @staticmethod
    def _dotted(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = _CallCollector._dotted(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        return None


def build_call_graph(root: Path) -> dict[str, set[str]]:
    """Returns qualname -> set of qualnames it calls (best-effort resolved)."""
    root = Path(root)
    all_defs: dict[str, ast.AST] = {}
    module_imports: dict[str, dict[str, str]] = {}
    func_bodies: dict[str, tuple[str, ast.AST]] = {}  # qualname -> (module, node)

    py_files = sorted(root.rglob("*.py"))
    for py_file in py_files:
        module = str(py_file.relative_to(root.parent)).replace("/", ".").replace("\\", ".")[:-3]
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        collector = _DefCollector(module)
        collector.visit(tree)
        for qn, node in collector.defs.items():
            all_defs[qn] = node
            func_bodies[qn] = (module, node)
        module_imports[module] = collector.imports

    graph: dict[str, set[str]] = {qn: set() for qn in all_defs}

    def _resolve(module: str, called_name: str) -> str | None:
        # 1. a function defined in the same module (possibly nested under a class — try both).
        candidate = f"{module}.{called_name}"
        if candidate in all_defs:
            return candidate
        # 2. via an import alias: called_name = "alias" or "alias.func"
        head, *rest = called_name.split(".", 1)
        imports = module_imports.get(module, {})
        if head in imports:
            resolved = imports[head] + ("." + rest[0] if rest else "")
            if resolved in all_defs:
                return resolved
        return None

    for qn, (module, node) in func_bodies.items():
        calls = _CallCollector()
        calls.visit(node)
        for called in calls.calls:
            resolved = _resolve(module, called)
            if resolved and resolved != qn:
                graph[qn].add(resolved)

    return graph


def transitive_callers(graph: dict[str, set[str]], target: str, max_hops: int = 3) -> set[str]:
    """Who (within `max_hops`) calls `target`, directly or transitively."""
    reverse: dict[str, set[str]] = {}
    for caller, callees in graph.items():
        for callee in callees:
            reverse.setdefault(callee, set()).add(caller)

    found: set[str] = set()
    frontier = {target}
    for _ in range(max_hops):
        next_frontier: set[str] = set()
        for node in frontier:
            for caller in reverse.get(node, ()):
                if caller not in found:
                    found.add(caller)
                    next_frontier.add(caller)
        frontier = next_frontier
        if not frontier:
            break
    return found
