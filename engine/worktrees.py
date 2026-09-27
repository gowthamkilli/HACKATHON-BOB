"""Isolated git checkouts for differential execution.

Every stage that needs to run code against a ref does it inside a `git worktree`, never inside
the user's own working tree. `create`/`create_merge` return a path; the caller is responsible
for calling `teardown` in a `finally` block.
"""
from __future__ import annotations

import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class WorktreeError(Exception):
    pass


class DirtyMainTreeError(Exception):
    """Raised when a harness operation is detected to have touched the user's own working tree."""


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def _scratch_root(repo: Path) -> Path:
    return repo.parent / ".wt"


@dataclass
class MainTreeSnapshot:
    head: str
    status: str


def _snapshot(repo: Path) -> MainTreeSnapshot:
    head = _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()
    status = _run(["git", "status", "--porcelain"], repo).stdout
    return MainTreeSnapshot(head=head, status=status)


def assert_main_tree_untouched(repo: Path, before: MainTreeSnapshot) -> None:
    after = _snapshot(repo)
    if after.head != before.head or after.status != before.status:
        raise DirtyMainTreeError(
            f"the main tree at {repo} changed during a harness operation "
            f"(HEAD {before.head}->{after.head}); this must never happen"
        )


def create(repo: Path, ref: str, label: Optional[str] = None) -> Path:
    """`git worktree add .wt/<label> <ref>` — a plain, single-ref checkout."""
    repo = Path(repo).resolve()
    before = _snapshot(repo)
    label = label or f"{ref.replace('/', '-')}-{uuid.uuid4().hex[:6]}"
    path = _scratch_root(repo) / label
    path.parent.mkdir(parents=True, exist_ok=True)
    result = _run(["git", "worktree", "add", "-q", "--detach", str(path), ref], repo)
    assert_main_tree_untouched(repo, before)
    if result.returncode != 0:
        raise WorktreeError(f"git worktree add failed for {ref}: {result.stderr}")
    return path


def create_merge(
    repo: Path, base: str, refs: list[str], label: Optional[str] = None
) -> tuple[Path, bool, bool]:
    """Check out `base`, then sequentially `git merge --no-commit --no-ff` each of `refs`.

    Returns (path, merged, conflict). `merged` is False (and `conflict` True) the moment any
    merge step reports a textual conflict — the caller should stop there, per §4 of the spec:
    a textual conflict is git's job, not Witness's.
    """
    path = create(repo, base, label=label)
    for ref in refs:
        result = _run(["git", "merge", "--no-commit", "--no-ff", ref], path)
        conflict = "CONFLICT" in result.stdout or "CONFLICT" in result.stderr
        if result.returncode != 0 or conflict:
            return path, False, True
    return path, True, False


def teardown(path: Path) -> None:
    """`git worktree remove --force`, always safe to call even if `path` is already gone.

    `git worktree remove` must be invoked with cwd inside *some* checkout of the same repo, not
    inside the worktree being removed itself — so this resolves the real repo root from the
    worktree's own `.git` file (`gitdir: <repo>/.git/worktrees/<label>`) rather than requiring
    the caller to remember it.
    """
    path = Path(path)
    if not path.exists():
        return
    repo_root = _find_repo_root(path)
    if repo_root is not None:
        _run(["git", "worktree", "remove", "--force", str(path)], repo_root)
        _run(["git", "worktree", "prune"], repo_root)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _find_repo_root(worktree_path: Path) -> Optional[Path]:
    git_file = worktree_path / ".git"
    if not git_file.is_file():
        return None
    content = git_file.read_text(encoding="utf-8").strip()
    if not content.startswith("gitdir:"):
        return None
    admin_dir = Path(content.split("gitdir:", 1)[1].strip())
    # admin_dir looks like <repo>/.git/worktrees/<label>
    if admin_dir.parent.name == "worktrees":
        return admin_dir.parent.parent.parent
    return None
