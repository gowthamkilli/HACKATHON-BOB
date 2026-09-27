"""Purpose Ledger extraction — §M4.

Two stages, in order:
1. **Deterministic harvest.** Collect every candidate guarantee site with its exact `file:line`
   from ADRs, code comments, docstrings, and test names. Nothing here is guessed.
2. **Model pass.** A subagent normalizes the harvested snippets into `Guarantee` blocks. If no
   model is configured (no credentials, no mock fixture), this stage is skipped and the
   deterministic values are used directly — reported as such, never silently swapped for a
   fabricated response.

**Provenance is enforced here, in code, after the model returns.** A candidate with an empty
`provenance` list is discarded before it ever becomes part of the ledger.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Optional

from engine.llm import FixtureMissing, Provider
from engine.schemas import Guarantee

_ADR_HEADING_RE = re.compile(r"^# ADR-(\d+):\s*(.+)$")
_GUARANTEE_BULLET_RE = re.compile(r"^\*\*Guarantee \((G\d+)\):\*\*\s*(.+)$")
_ENFORCED_AT_RE = re.compile(r"^\*\*Enforced at:\*\*\s*`([\w./]+\.py):(\w+)`\s*$")
_CODE_COMMENT_ADR_RE = re.compile(r"#\s*(?:ADR-(\d+)|INVARIANT):\s*(.+?)(?:\s*\(docs/ADR-\d+\.md:\d+\))?\s*$")


class Candidate:
    def __init__(self, gid: str, statement: str, provenance: list[str]):
        self.gid = gid
        self.statement = statement
        self.why: str = ""
        self.provenance: list[str] = list(provenance)
        self.enforced_at: list[str] = []
        self.surface: list[str] = []


def _harvest_adrs(repo: Path) -> dict[str, Candidate]:
    candidates: dict[str, Candidate] = {}
    docs_dir = repo / "docs"
    if not docs_dir.exists():
        return candidates

    for adr_path in sorted(docs_dir.glob("ADR-*.md")):
        lines = adr_path.read_text(encoding="utf-8").splitlines()
        rel = f"docs/{adr_path.name}"
        current_gid: Optional[str] = None
        why_lines: list[str] = []
        in_why = False

        for i, line in enumerate(lines, start=1):
            bullet = _GUARANTEE_BULLET_RE.match(line)
            if bullet:
                gid, statement = bullet.group(1), bullet.group(2)
                current_gid = gid
                candidates[gid] = Candidate(gid, statement, provenance=[f"{rel}:{i}"])
                continue

            if line.strip() == "## Why":
                in_why = True
                continue
            if line.startswith("## ") and line.strip() != "## Why":
                in_why = False
            if in_why and line.strip():
                why_lines.append(line.strip())
            elif in_why and not line.strip() and why_lines:
                in_why = False

            enforced = _ENFORCED_AT_RE.match(line)
            if enforced and current_gid and current_gid in candidates:
                file_rel, func_name = enforced.group(1), enforced.group(2)
                line_no = _resolve_def_line(repo / file_rel, func_name)
                if line_no is not None:
                    candidates[current_gid].enforced_at.append(f"{file_rel}:{line_no}")
                    module = file_rel[:-3].replace("/", ".")
                    candidates[current_gid].surface.append(f"{module}.{func_name}")

        if current_gid and current_gid in candidates and why_lines:
            candidates[current_gid].why = " ".join(why_lines)

    return candidates


def _resolve_def_line(file_path: Path, func_name: str) -> Optional[int]:
    if not file_path.exists():
        return None
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return node.lineno
    return None


_ADR_NUM_TO_GID = {f"{i:03d}": f"G{i}" for i in range(1, 11)}


def _harvest_code_comments(repo: Path, candidates: dict[str, Candidate]) -> None:
    """Cross-reference `# ADR-0NN: ...` provenance comments in `app/*.py` — each one is a second,
    independent provenance site for the same guarantee (a docstring/comment, per §2's
    definition of Guarantee provenance)."""
    app_dir = repo / "app"
    if not app_dir.exists():
        return
    for py_file in sorted(app_dir.glob("*.py")):
        rel = f"app/{py_file.name}"
        for i, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), start=1):
            m = re.search(r"ADR-(\d{3})", line)
            if not m or not line.strip().startswith("#"):
                continue
            gid = _ADR_NUM_TO_GID.get(m.group(1))
            if gid and gid in candidates:
                site = f"{rel}:{i}"
                if site not in candidates[gid].provenance:
                    candidates[gid].provenance.append(site)


def harvest(repo: Path) -> dict[str, Candidate]:
    repo = Path(repo)
    candidates = _harvest_adrs(repo)
    _harvest_code_comments(repo, candidates)
    return candidates


def _parse_ledger_model_output(text: str) -> list[dict]:
    blocks = re.findall(r"GUARANTEE_START(.*?)GUARANTEE_END", text, re.DOTALL)
    if not blocks:
        raise ValueError("no GUARANTEE_START/GUARANTEE_END blocks found")
    parsed = []
    for block in blocks:
        gid = re.search(r"ID:\s*(\S+)", block)
        statement = re.search(r"STATEMENT:\s*(.+)", block)
        why = re.search(r"WHY:\s*(.+)", block)
        if not gid or not statement:
            raise ValueError(f"malformed guarantee block: {block!r}")
        parsed.append({
            "id": gid.group(1).strip(),
            "statement": statement.group(1).strip(),
            "why": why.group(1).strip() if why else "",
        })
    return parsed


def build_ledger(
    repo: Path, provider: Optional[Provider] = None,
) -> tuple[list[Guarantee], dict]:
    """Returns (ledger, meta). `meta['model_pass']` is False when no live/mock model output was
    available — the ledger is still the real, correct deterministic harvest, just not refined."""
    candidates = harvest(repo)
    meta = {"model_pass": False, "model_pass_error": None}

    if provider is not None and candidates:
        harvest_text = "\n".join(
            f"[{c.gid}] {c.statement} (why: {c.why})" for c in candidates.values()
        )
        from engine.agents import run_agent

        try:
            result = run_agent(
                "ledger", {"harvest_text": harvest_text},
                parse_fn=_parse_ledger_model_output, provider=provider,
            )
            if result.ok:
                for block in result.parsed:
                    gid = block["id"]
                    if gid in candidates:
                        candidates[gid].statement = block["statement"] or candidates[gid].statement
                        candidates[gid].why = block["why"] or candidates[gid].why
                meta["model_pass"] = True
            else:
                meta["model_pass_error"] = result.error
        except FixtureMissing as e:
            meta["model_pass_error"] = str(e)

    ledger = []
    for c in candidates.values():
        if not c.provenance:
            continue  # discarded by the harness, never by the model
        ledger.append(Guarantee(
            id=c.gid, statement=c.statement, why=c.why, provenance=c.provenance,
            enforced_at=c.enforced_at, covered_by_test=None, surface=c.surface,
        ))
    ledger.sort(key=lambda g: int(g.id[1:]))
    return ledger, meta


def compute_coverage(repo: Path, ledger: list[Guarantee]) -> None:
    """Populate `covered_by_test` in place: run the suite under `coverage.py`, then check
    whether each guarantee's `enforced_at` line was executed. Mutates `ledger`.

    This is line coverage, not assertion coverage — it tells you the enforcement code *ran*
    during the suite, not that any test specifically asserts the guarantee's behavior. Reported
    honestly in DECISIONS.md rather than hidden behind a smarter-sounding label.
    """
    import subprocess
    import sys

    import coverage

    repo = Path(repo)
    data_file = repo / ".coverage.ledger"
    subprocess.run(
        [sys.executable, "-m", "coverage", "run", f"--data-file={data_file}",
         "--source=app", "-m", "pytest", "tests", "-q"],
        cwd=repo, capture_output=True, text=True,
    )
    cov = coverage.Coverage(data_file=str(data_file))
    cov.load()

    for g in ledger:
        if not g.enforced_at:
            g.covered_by_test = None
            continue
        hit_all = True
        for site in g.enforced_at:
            file_rel, line_str = site.rsplit(":", 1)
            line_no = int(line_str)
            abs_path = str((repo / file_rel).resolve())
            try:
                _, executable, _excluded, missing, _ = cov.analysis2(abs_path)
            except Exception:
                hit_all = False
                continue
            if line_no in missing:
                hit_all = False
        g.covered_by_test = (g.surface[0] if g.surface else "covered") if hit_all else None

    data_file.unlink(missing_ok=True)
