"""Blast radius — 5 parallel subagents (§9, M7).

Each subagent reads what it needs on its own side and returns parsed `BlastFinding` blocks —
raw file contents never cross back into the parent context. A finding with empty `evidence` is
dropped by the harness here, not trusted from the model.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from engine import callgraph
from engine.agents import run_agents_parallel
from engine.llm import Provider
from engine.schemas import BlastFinding, ChangeSpec

_FINDING_RE = re.compile(r"FINDING_START(.*?)FINDING_END", re.DOTALL)


def parse_findings(text: str) -> list[dict]:
    """Shared return grammar for all 5 blast-radius prompts. An empty result (no blocks at all)
    is valid — silence is a correct output, not a parse failure."""
    blocks = []
    for raw in _FINDING_RE.findall(text):
        subject = re.search(r"SUBJECT:[ \t]*(.+)", raw)
        claim = re.search(r"CLAIM:[ \t]*(.+)", raw)
        evidence = re.search(r"EVIDENCE:[ \t]*(.*)", raw)
        severity = re.search(r"SEVERITY:[ \t]*(\d)", raw)
        mechanism = re.search(r"MECHANISM:[ \t]*(\w+)", raw)
        if not subject or not claim:
            raise ValueError(f"malformed finding block: {raw!r}")
        ev_list = [e.strip() for e in (evidence.group(1).split(",") if evidence else []) if e.strip()]
        blocks.append({
            "subject": subject.group(1).strip(), "claim": claim.group(1).strip(),
            "evidence": ev_list, "severity": int(severity.group(1)) if severity else 0,
            "mechanism": mechanism.group(1).strip().lower() if mechanism else None,
        })
    return blocks


def _read_function_source(root: Path, qualname: str, rel_file: str) -> str:
    path = root / rel_file
    if not path.exists():
        return ""
    func_name = qualname.rsplit(".", 1)[-1]
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^\s*(async def|def)\s+{re.escape(func_name)}\s*\(", line):
            start = i
            break
    if start is None:
        return ""
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].strip() and (len(lines[j]) - len(lines[j].lstrip())) <= indent:
            end = j
            break
    return "\n".join(lines[start:end])


def _git_diff(repo: Path, base: str, ref: str) -> str:
    result = subprocess.run(["git", "diff", f"{base}..{ref}"], cwd=repo, capture_output=True, text=True)
    return result.stdout[:6000]


def _log_excerpt(repo: Path, files: list[str]) -> str:
    if not files:
        return "(no files)"
    result = subprocess.run(
        ["git", "log", "--oneline", "-20", "--", *files], cwd=repo, capture_output=True, text=True,
    )
    return result.stdout or "(no history)"


def run_blast_radius(
    change_spec: ChangeSpec, repo: Path, base_wt: Path, merged_wt: Path, *,
    provider: Provider, bus_run_id: Optional[str] = None,
) -> list[BlastFinding]:
    graph = callgraph.build_call_graph(merged_wt / "app")
    touched_qualnames = [s.qualname for s in change_spec.symbols_touched]

    callers_ctx: dict[str, str] = {}
    for qn in touched_qualnames:
        callers = callgraph.transitive_callers(graph, qn, max_hops=3)
        if callers:
            callers_ctx[qn] = ", ".join(sorted(callers))

    contract_lines = []
    for s in change_spec.symbols_touched:
        base_src = _read_function_source(base_wt, s.qualname, s.file)
        head_src = _read_function_source(merged_wt, s.qualname, s.file)
        contract_lines.append(f"### {s.qualname} ({s.file}:{s.line})\nBASE:\n{base_src}\nHEAD:\n{head_src}")

    state_lines = [f"{t.kind} {t.name} ({t.file}:{t.line})" for t in change_spec.state_touched]

    branch_a = change_spec.head_ref
    branch_b = change_spec.with_refs[0] if change_spec.with_refs else None

    specs = [
        {"name": "callers", "context": {
            "symbols": "\n".join(touched_qualnames),
            "callgraph": "\n".join(f"{qn} <- {c}" for qn, c in callers_ctx.items()) or "(no callers found)",
        }, "parse_fn": parse_findings},
        {"name": "contract", "context": {
            "base_code": "", "head_code": "\n\n".join(contract_lines),
        }, "parse_fn": parse_findings},
        {"name": "state", "context": {
            "state_touched": "\n".join(state_lines) or "(none)",
            "symbols": "\n".join(touched_qualnames),
        }, "parse_fn": parse_findings},
        {"name": "history", "context": {
            "symbols": "\n".join(touched_qualnames),
            "log_excerpt": _log_excerpt(repo, change_spec.files_changed),
        }, "parse_fn": parse_findings},
        {"name": "merge-intent", "context": {
            "branch_a_diff": _git_diff(repo, change_spec.base_ref, branch_a),
            "branch_b_diff": _git_diff(repo, change_spec.base_ref, branch_b) if branch_b else "(single branch — no B side)",
        }, "parse_fn": parse_findings},
    ]

    results = run_agents_parallel(specs, max_workers=5, provider=provider, bus_run_id=bus_run_id, stage="blast")

    findings: list[BlastFinding] = []
    for result in results:
        if not result.ok:
            continue
        for block in result.parsed:
            if not block["evidence"]:
                continue  # dropped by the harness, not reported
            findings.append(BlastFinding(
                agent=result.agent, subject=block["subject"], claim=block["claim"],
                evidence=block["evidence"], severity_hint=block["severity"],
                tokens_used=result.completion_tokens, elapsed_s=result.elapsed_s,
            ))
    return findings
