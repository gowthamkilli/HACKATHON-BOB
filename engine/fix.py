"""The fix stage (§9, M10). Witness writes tests; humans merge fixes — the patch is proposed,
never auto-applied to the user's tree. This module only ever writes into a worktree.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from engine.execute import run_test
from engine.llm import Provider
from engine.schemas import FixPatch

_DIFF_RE = re.compile(r"DIFF_START(.*?)DIFF_END", re.DOTALL)
MAX_ATTEMPTS = 3


def parse_fix_response(text: str) -> str:
    match = _DIFF_RE.search(text)
    diff = match.group(1).strip("\n") if match else text.strip()
    if "diff --git" not in diff and "---" not in diff:
        raise ValueError("response doesn't look like a unified diff")
    return diff


def _diff_stats(diff_text: str) -> tuple[int, int, list[str]]:
    added = sum(1 for l in diff_text.splitlines() if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff_text.splitlines() if l.startswith("-") and not l.startswith("---"))
    files = sorted({
        m.group(1) for m in re.finditer(r"^\+\+\+ b/(.+)$", diff_text, re.MULTILINE)
    })
    return added, removed, files


def apply_patch(worktree: Path, diff_text: str) -> tuple[bool, str]:
    patch_file = worktree / ".witness-fix.patch"
    text = diff_text if diff_text.endswith("\n") else diff_text + "\n"
    # newline="" avoids Python's own text-mode CRLF translation on Windows on top of git diff's
    # own LF-only hunks; --ignore-space-at-eol handles core.autocrlf=true checkouts, where the
    # working tree's context lines are CRLF but the diff's are LF.
    with open(patch_file, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    try:
        check = subprocess.run(
            ["git", "apply", "--check", "--ignore-whitespace", str(patch_file)],
            cwd=worktree, capture_output=True, text=True,
        )
        if check.returncode != 0:
            return False, check.stderr
        apply = subprocess.run(
            ["git", "apply", "--ignore-whitespace", str(patch_file)],
            cwd=worktree, capture_output=True, text=True,
        )
        if apply.returncode != 0:
            return False, apply.stderr
        return True, ""
    finally:
        patch_file.unlink(missing_ok=True)


def attempt_fix(
    candidate_id: str, proof_test_path: Path, failing_output: str, invariant_delta_text: str,
    head_diff: str, head_wt: Path, full_suite_dir: str = "tests", *, provider: Provider,
) -> FixPatch:
    """Cap at 3 attempts; on `git apply` failure, regenerate once with the error appended, then
    abandon. Prefer the smallest accepted patch (caller can compare across candidates)."""
    from engine.agents import run_agent

    context = {
        "proof_test": proof_test_path.read_text(encoding="utf-8"),
        "failing_output": failing_output, "invariant_delta": invariant_delta_text,
        "head_diff": head_diff,
    }

    suite_before = run_test(head_wt, proof_test_path, timeout=120).status  # expected FAIL

    last_reason = None
    for attempt in range(MAX_ATTEMPTS):
        result = run_agent("fix", context, parse_fn=parse_fix_response, provider=provider, max_tokens=1200)
        if not result.ok:
            last_reason = f"fix generation failed: {result.error}"
            continue

        diff_text = result.parsed
        applied, apply_error = apply_patch(head_wt, diff_text)
        if not applied:
            context["failing_output"] += f"\n\ngit apply failed: {apply_error}"
            last_reason = f"patch did not apply: {apply_error[:200]}"
            continue

        proof_after = run_test(head_wt, proof_test_path, timeout=120)
        suite_after = _run_full_suite(head_wt, full_suite_dir)

        if proof_after.status == "PASS" and suite_after == "PASS":
            added, removed, files = _diff_stats(diff_text)
            return FixPatch(
                candidate_id=candidate_id, unified_diff=diff_text, files_touched=files,
                lines_added=added, lines_removed=removed, suite_before=suite_before,
                proof_test_after=proof_after.status, suite_after=suite_after, accepted=True,
            )

        _git_checkout_all(head_wt)  # undo the rejected patch before the next attempt
        last_reason = f"proof_after={proof_after.status} suite_after={suite_after}"

    return FixPatch(
        candidate_id=candidate_id, unified_diff="", files_touched=[], lines_added=0,
        lines_removed=0, suite_before=suite_before, proof_test_after="FAIL", suite_after="UNKNOWN",
        accepted=False, rejection_reason=last_reason,
    )


def _run_full_suite(worktree: Path, suite_dir: str) -> str:
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pytest", suite_dir, "-q"], cwd=worktree, capture_output=True, text=True,
    )
    return "PASS" if result.returncode == 0 else "FAIL"


def _git_checkout_all(worktree: Path) -> None:
    subprocess.run(["git", "checkout", "--", "."], cwd=worktree, capture_output=True, text=True)
