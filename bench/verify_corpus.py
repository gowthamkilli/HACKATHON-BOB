"""M2 acceptance: mechanically verify all 8 branch pairs satisfy conditions (i)-(iii):

  (i)   each branch is green alone
  (ii)  git merge reports zero textual conflict
  (iii) the merged suite is also green

Condition (iv) (a documented guarantee is genuinely defeated) is verified by hand per pair and
recorded in DECISIONS.md — this script only checks the mechanical, branch-independent facts.

Usage: python bench/verify_corpus.py [--repo path/to/samples/orderworks]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

PAIRS = [
    ("team-a/rate-limit", ["team-b/retry"]),
    ("team-c/bulk-endpoint", []),
    ("team-b/write-through", ["team-d/cache-warm"]),
    ("team-a/idempotency-v2", ["team-c/request-id"]),
    ("team-d/async-notify", ["team-b/retry-state-handler"]),
    ("team-a/audit-compact", ["team-c/soft-delete"]),
    ("team-b/pagination", ["team-d/query-builder"]),
    ("team-a/discounts", ["team-c/tax"]),
]


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def run_pytest(repo: Path, python: str) -> bool:
    result = subprocess.run([python, "-m", "pytest", "tests", "-q"], cwd=repo, capture_output=True, text=True)
    return result.returncode == 0


def verify_pair(repo: Path, base: str, with_refs: list[str], python: str) -> dict:
    label = base.replace("/", "-")
    scratch = repo.parent / f".verify-{label}-{uuid.uuid4().hex[:6]}"
    result = {"base": base, "with": with_refs, "green_alone": None, "zero_conflict": None, "green_merged": None}

    run(["git", "worktree", "add", "-q", "--detach", str(scratch), base], cwd=repo)
    try:
        result["green_alone"] = run_pytest(scratch, python)

        if with_refs:
            merge_res = subprocess.run(
                ["git", "merge", "--no-commit", "--no-ff", *with_refs],
                cwd=scratch, capture_output=True, text=True,
            )
            result["zero_conflict"] = merge_res.returncode == 0 and "CONFLICT" not in merge_res.stdout
            result["green_merged"] = result["zero_conflict"] and run_pytest(scratch, python)
        else:
            # single-branch pair: base merged with main IS the branch itself
            result["zero_conflict"] = True
            result["green_merged"] = result["green_alone"]
    finally:
        run(["git", "merge", "--abort"], cwd=scratch)
        run(["git", "worktree", "remove", "--force", str(scratch)], cwd=repo)
        run(["git", "worktree", "prune"], cwd=repo)
        shutil.rmtree(scratch, ignore_errors=True)

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1] / "samples" / "orderworks"))
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    repo = Path(args.repo).resolve()

    all_ok = True
    for base, with_refs in PAIRS:
        r = verify_pair(repo, base, with_refs, args.python)
        ok = r["green_alone"] and r["zero_conflict"] and r["green_merged"]
        all_ok = all_ok and ok
        status = "PASS" if ok else "FAIL"
        pair_desc = base if not with_refs else f"{base} + {'+'.join(with_refs)}"
        print(f"[{status}] {pair_desc}  green_alone={r['green_alone']} "
              f"zero_conflict={r['zero_conflict']} green_merged={r['green_merged']}")

    print()
    print("ALL PAIRS OK" if all_ok else "SOME PAIRS FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
