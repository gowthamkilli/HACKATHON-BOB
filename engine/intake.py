"""Intake — ChangeSpec (premortem) and IncidentSpec (postmortem) construction.

§4: "If there is a textual conflict, stop and say so — git already caught that one and Witness
adds nothing." That early-exit is a feature of the thesis, not a shortcut: knowing what *not* to
report is part of the point.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from typing import Optional

from engine import surface, worktrees
from engine.schemas import ChangeSpec, IncidentSpec, StackFrame, StateTouch, SymbolChange

_MODAL_HINT = re.compile(r"\bos\.(environ\[|getenv\()")
_DDL_HINT = re.compile(r"\b(CREATE|ALTER)\s+TABLE\b", re.IGNORECASE)


class _SymbolInfo:
    def __init__(self, kind: str, line: int, signature: Optional[str], body_hash: int):
        self.kind = kind
        self.line = line
        self.signature = signature
        self.body_hash = body_hash


def _extract_symbols(file_path: Path) -> dict[str, _SymbolInfo]:
    if not file_path.exists():
        return {}
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return {}

    module = file_path.stem
    result: dict[str, _SymbolInfo] = {}

    def visit(node: ast.AST, scope: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = ".".join([module] + scope + [child.name])
                kind = "method" if scope else "function"
                sig = ast.unparse(child.args)
                body_dump = "\n".join(ast.dump(n) for n in child.body)
                result[qualname] = _SymbolInfo(kind, child.lineno, sig, hash(body_dump))
                visit(child, scope + [child.name])
            elif isinstance(child, ast.ClassDef):
                qualname = ".".join([module] + scope + [child.name])
                result[qualname] = _SymbolInfo("class", child.lineno, None, hash(child.name))
                visit(child, scope + [child.name])
            elif isinstance(child, ast.Assign) and not scope:
                for target in child.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        qualname = ".".join([module] + [target.id])
                        result[qualname] = _SymbolInfo(
                            "module_const", child.lineno, None, hash(ast.dump(child.value))
                        )

    visit(tree, [])
    return result


def _diff_symbols(rel_path: str, base_file: Path, head_file: Path) -> list[SymbolChange]:
    base_syms = _extract_symbols(base_file)
    head_syms = _extract_symbols(head_file)
    changes: list[SymbolChange] = []

    for qn, info in head_syms.items():
        if qn not in base_syms:
            changes.append(SymbolChange(
                qualname=qn, file=rel_path, line=info.line, kind=info.kind, change="added",
                old_signature=None, new_signature=info.signature,
            ))
        else:
            old = base_syms[qn]
            if info.signature != old.signature:
                changes.append(SymbolChange(
                    qualname=qn, file=rel_path, line=info.line, kind=info.kind,
                    change="signature_changed", old_signature=old.signature, new_signature=info.signature,
                ))
            elif info.body_hash != old.body_hash:
                changes.append(SymbolChange(
                    qualname=qn, file=rel_path, line=info.line, kind=info.kind,
                    change="body_changed", old_signature=old.signature, new_signature=info.signature,
                ))

    for qn, info in base_syms.items():
        if qn not in head_syms:
            changes.append(SymbolChange(
                qualname=qn, file=rel_path, line=info.line, kind=info.kind, change="removed",
                old_signature=info.signature, new_signature=None,
            ))

    return changes


def _state_touched_in_file(rel_path: str, file_path: Path) -> list[StateTouch]:
    if not file_path.exists():
        return []
    text = file_path.read_text(encoding="utf-8")
    touches: list[StateTouch] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return touches

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(getattr(node, "col_offset", None), int):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    touches.append(StateTouch(kind="module_const", name=target.id,
                                               file=rel_path, line=node.lineno))
        if isinstance(node, ast.Call):
            dotted = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
            if "os.environ" in dotted or "os.getenv" in dotted:
                arg = node.args[0] if node.args else None
                name = ast.literal_eval(arg) if isinstance(arg, ast.Constant) else "?"
                touches.append(StateTouch(kind="env", name=str(name), file=rel_path, line=node.lineno))

    for i, line in enumerate(text.splitlines(), start=1):
        if _DDL_HINT.search(line):
            touches.append(StateTouch(kind="sql_table", name=line.strip()[:60], file=rel_path, line=i))

    return touches


def _introduced_by(repo: Path, symbol_name: str, base: str, refs: list[str]) -> Optional[str]:
    for ref in refs:
        result = subprocess.run(
            ["git", "log", "--format=%H", f"-S{symbol_name}", f"{base}..{ref}"],
            cwd=repo, capture_output=True, text=True,
        )
        if result.stdout.strip():
            return ref
    return None


def build_change_spec(repo: Path, base: str, head: str, with_refs: Optional[list[str]] = None) -> ChangeSpec:
    repo = Path(repo)
    with_refs = with_refs or []
    all_refs = [head] + with_refs

    merged_wt, merged, conflict = worktrees.create_merge(repo, base, all_refs, label="intake-merged")
    if conflict:
        worktrees.teardown(merged_wt)
        return ChangeSpec(base_ref=base, head_ref=head, with_refs=with_refs, textual_conflict=True)

    base_wt = worktrees.create(repo, base, label="intake-base")
    try:
        diff_result = subprocess.run(
            ["git", "diff", "--name-only", base], cwd=merged_wt, capture_output=True, text=True,
        )
        files_changed = [f for f in diff_result.stdout.splitlines() if f.endswith(".py")]

        symbols_touched: list[SymbolChange] = []
        state_touched: list[StateTouch] = []
        introduced_by: dict[str, str] = {}

        for rel_path in files_changed:
            base_file = base_wt / rel_path
            head_file = merged_wt / rel_path
            changes = _diff_symbols(rel_path, base_file, head_file)
            symbols_touched.extend(changes)
            state_touched.extend(_state_touched_in_file(rel_path, head_file))

            for change in changes:
                short_name = change.qualname.rsplit(".", 1)[-1]
                ref = _introduced_by(repo, short_name, base, all_refs)
                if ref:
                    introduced_by[change.qualname] = ref

        shared = surface.shared_surface(base_wt / "app", merged_wt / "app")

        return ChangeSpec(
            base_ref=base, head_ref=head, with_refs=with_refs, textual_conflict=False,
            files_changed=files_changed, symbols_touched=symbols_touched,
            state_touched=state_touched, introduced_by=introduced_by, shared_surface=shared,
        )
    finally:
        worktrees.teardown(base_wt)
        worktrees.teardown(merged_wt)


_TRACEBACK_FRAME_RE = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')


def build_incident_spec(text_or_path: str) -> IncidentSpec:
    """Extract stack frames and error info from a traceback (pasted text), a `.pdf` export, or
    plain prose with no stack trace at all (in which case `stack_frames` is empty and
    `suspect_symbols` carries whatever the postmortem recon agents will have to work with)."""
    path = Path(text_or_path)
    if path.suffix.lower() == ".pdf" and path.exists():
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        raw_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        source = "pdf"
        title = path.stem
    elif path.exists():
        raw_text = path.read_text(encoding="utf-8")
        source = "issue"
        title = path.stem
    else:
        raw_text = text_or_path
        source = "issue"
        title = raw_text.strip().splitlines()[0][:80] if raw_text.strip() else "incident"

    frames = [
        StackFrame(file=m.group(1), line=int(m.group(2)), qualname=m.group(3))
        for m in _TRACEBACK_FRAME_RE.finditer(raw_text)
    ]
    if frames:
        source = "stacktrace" if source == "issue" else source

    error_match = re.search(r"^(\w+(?:\.\w+)*Error):\s*(.+)$", raw_text, re.MULTILINE)
    error_type = error_match.group(1) if error_match else None
    error_message = error_match.group(2) if error_match else None

    return IncidentSpec(
        title=title, raw_text=raw_text, source=source, stack_frames=frames,
        error_type=error_type, error_message=error_message,
        suspect_symbols=[f.qualname for f in frames],
        observed_at_ref="",
    )
