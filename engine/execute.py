"""Run one test file against one worktree and classify the result.

The one rule that makes this trustworthy: **a collection/import error is never scored as a
`FAIL`.** A test that can't even be collected proved nothing about the code under test — it's
`ERROR`, and `confirm.py` treats `ERROR` on base as `INVALID`, never a win.
"""
from __future__ import annotations

import dataclasses
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


@dataclasses.dataclass
class ExecResult:
    status: str  # PASS | FAIL | ERROR | TIMEOUT
    exit_code: Optional[int]
    stderr_excerpt: str
    elapsed_s: float
    touched_app_source: bool
    stdout_tail: str = ""


def _looks_like_collection_error(output: str) -> bool:
    return (
        "errors during collection" in output
        or "ERROR collecting" in output
        or "INTERNALERROR" in output
        or ("error" in output.lower() and "collected 0 items" in output)
    )


def _kill_tree(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True, text=True,
        )
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _popen_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"preexec_fn": os.setsid}


def run_test(worktree: Path, test_file: Path, timeout: int = 120) -> ExecResult:
    """Copy `test_file` into `<worktree>/tests/`, run it with pytest, classify the outcome.

    After the run, `<worktree>`'s git status is checked: any change outside `tests/` sets
    `touched_app_source=True` — a lane that does this is rejected regardless of its verdict
    (§9, M9's `confirm.py`), enforced here rather than trusted from the prompt.
    """
    worktree = Path(worktree)
    baseline_status = _git_status_lines(worktree)  # a --no-commit merge can already be "dirty"
    tests_dir = worktree / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    dest = tests_dir / Path(test_file).name
    shutil.copy(test_file, dest)

    start = time.monotonic()
    cmd = [sys.executable, "-m", "pytest", str(dest.relative_to(worktree)),
           "-x", "-q", "--no-header", "-p", "no:cacheprovider"]
    proc = subprocess.Popen(
        cmd, cwd=worktree, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        **_popen_kwargs(),
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        elapsed = time.monotonic() - start
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        elapsed = time.monotonic() - start
        touched = _check_touched_app_source(worktree, baseline_status)
        return ExecResult(status="TIMEOUT", exit_code=None, stderr_excerpt="",
                           elapsed_s=elapsed, touched_app_source=touched)

    combined = (stdout or "") + "\n" + (stderr or "")
    touched = _check_touched_app_source(worktree, baseline_status)

    if exit_code == 0:
        status = "PASS"
    elif _looks_like_collection_error(combined):
        status = "ERROR"
    else:
        status = "FAIL"

    return ExecResult(
        status=status, exit_code=exit_code, stderr_excerpt=(stderr or "")[-400:],
        elapsed_s=elapsed, touched_app_source=touched, stdout_tail=(stdout or "")[-800:],
    )


def _git_status_lines(worktree: Path) -> set[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain"], cwd=worktree, capture_output=True, text=True,
    )
    return set(result.stdout.splitlines())


def _check_touched_app_source(worktree: Path, baseline: set[str]) -> bool:
    """A `--no-commit --no-ff` merge worktree can already be "dirty" before any test runs — only
    lines that are NEW relative to that baseline count as something *the test* touched."""
    new_lines = _git_status_lines(worktree) - baseline
    for line in new_lines:
        path_part = line[3:].strip()
        if not path_part.startswith("tests/") and not path_part.startswith("tests\\"):
            return True
    return False
