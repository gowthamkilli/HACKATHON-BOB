"""The Honesty Invariant (§3), enforced by a test, not by intent.

Over every *pipeline* file in `engine/` (see scope note below):
  1. No identifier and no string literal contains any of the forbidden tokens, or a guarantee-id
     shaped token (`G\\d+`). Guarantee IDs are data, read from the ledger at runtime — never code.
  2. No function name matches `_has_.*_in_(head|base)` or `_detect_.*_case`.
  3. No module under `engine/` imports anything from `bench/` or `samples/`.

If this test can only be made to pass by adding a case-specific branch, the milestone that
needed it has failed — fix the general mechanism instead.

**Scope note 1 — identifiers/literals, not prose.** The spec's own wording is "no identifier
and no string literal" — this checks Python identifiers (names, function/class/arg names) and
string literal *values*, via the AST, not arbitrary comment or docstring prose. A docstring is
free to use an ordinary English word like "retry" to describe this module's own generic
mechanism (e.g. `agents.py`'s retry-on-parse-failure, which has nothing to do with any benchmark
case); comments aren't part of the AST at all and are naturally excluded. What's actually
forbidden is a hardcoded identifier or string constant that names a specific case, e.g. a
variable `is_retry_branch` or a compared string `"team-b/retry"` — hardcoded detection logic,
not English prose describing what the code in front of it does.

**Scope note 2 — pipeline modules, not the test suite.** This scans `engine/`'s pipeline
modules (`cli.py`, `agents.py`, `intake.py`, `ledger.py`, ...) — not `engine/tests/`. The spec's
own M3/M9 acceptance sections explicitly hand-write tests that pass real branch names
(`team-a/rate-limit`, etc.) as *parameters* to prove the general mechanism against the real
corpus — that is what an acceptance test is for. Passing "team-a/rate-limit" as a plain string
argument to `worktrees.create(repo, ref, label)` is not case-specific logic in the engine; a
pipeline module branching on that string internally would be.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {"fixtures", "tests"}

FORBIDDEN_TOKENS = [
    "retry", "bulk", "limiter", "idempoten", "write_through", "ceiling",
    "team-a", "team-b", "team-c", "case-0",
]
GUARANTEE_ID_RE = re.compile(r"^G\d{1,2}$")
FORBIDDEN_FUNC_NAME_RES = [
    re.compile(r"_has_.*_in_(head|base)"),
    re.compile(r"_detect_.*_case"),
]


def _engine_py_files():
    for path in ENGINE_DIR.rglob("*.py"):
        parts = path.relative_to(ENGINE_DIR).parts
        if EXCLUDED_DIRS & set(parts):
            continue
        yield path


def _is_forbidden(text: str) -> bool:
    lowered = text.lower()
    if any(token in lowered for token in FORBIDDEN_TOKENS):
        return True
    return bool(GUARANTEE_ID_RE.match(text))


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Node ids of string-constant docstrings, so they're excluded from the literal check."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def test_no_forbidden_identifiers_or_string_literals():
    violations = []
    for path in _engine_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstring_ids = _docstring_nodes(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and _is_forbidden(node.id):
                violations.append(f"{path}:{node.lineno}: identifier {node.id!r}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and _is_forbidden(node.name):
                violations.append(f"{path}:{node.lineno}: definition {node.name!r}")
            elif isinstance(node, ast.arg) and _is_forbidden(node.arg):
                violations.append(f"{path}:{node.lineno}: argument {node.arg!r}")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstring_ids:
                if _is_forbidden(node.value):
                    violations.append(f"{path}:{node.lineno}: string literal {node.value!r}")

    assert not violations, "\n".join(violations)


def test_no_case_detection_function_names():
    violations = []
    for path in _engine_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for pattern in FORBIDDEN_FUNC_NAME_RES:
                    if pattern.search(node.name):
                        violations.append(f"{path}:{node.lineno}: forbidden function name {node.name!r}")
    assert not violations, "\n".join(violations)


def test_no_engine_module_imports_from_bench_or_samples():
    violations = []
    for path in _engine_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.startswith("bench") or name.startswith("samples"):
                    violations.append(f"{path}:{node.lineno}: imports {name!r}")
    assert not violations, "\n".join(violations)
