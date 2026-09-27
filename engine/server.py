"""FastAPI server backing Witness Studio (§9, M12).

Every event is appended to `runs/run-<id>.jsonl` as published (by `engine/events.py`), so a
reconnecting client and `witness replay` read the identical sequence from disk.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from engine import events, ledger as ledger_module
from engine.pipeline import run_postmortem, run_premortem, run_standing
from engine.schemas import Run

app = FastAPI(title="Witness")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_repos: dict[str, Path] = {}
_runs: dict[str, Run] = {}
_run_status: dict[str, str] = {}  # "running" | "done" | "error"


class ConnectRepoRequest(BaseModel):
    path: str


class CreateBranchRequest(BaseModel):
    name: str
    from_ref: str


class WriteFileRequest(BaseModel):
    branch: str
    path: str
    content: str


class ApplyPatchRequest(BaseModel):
    branch: str
    unified_diff: str


class PremortemRequest(BaseModel):
    repo_id: str
    base: str
    head: str
    with_: list[str] = []
    fix: bool = False
    provider: str = "mock"


class PostmortemRequest(BaseModel):
    repo_id: str
    ref: str = "HEAD"
    incident_text: Optional[str] = None
    provider: str = "mock"


def _repo_or_404(repo_id: str) -> Path:
    repo = _repos.get(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="unknown repo_id")
    return repo


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


@app.get("/api/health")
def health():
    fixtures_dir = Path("engine/fixtures")
    provider = os.environ.get("WITNESS_DEFAULT_PROVIDER", "watsonx")
    return {
        "ok": True, "provider": provider,
        "model": os.environ.get("WATSONX_MODEL_ID", ""),
        "fixtures": fixtures_dir.exists() and any(fixtures_dir.iterdir()) if fixtures_dir.exists() else False,
    }


@app.post("/api/repo/connect")
def connect_repo(req: ConnectRepoRequest):
    path = Path(req.path).resolve()
    if not (path / ".git").exists():
        raise HTTPException(status_code=400, detail=f"{path} is not a git repository")
    repo_id = uuid.uuid4().hex[:8]
    _repos[repo_id] = path

    branches = _git(path, "branch", "--format=%(refname:short)").stdout.splitlines()
    head = _git(path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    dirty = bool(_git(path, "status", "--porcelain").stdout.strip())
    return {"repo_id": repo_id, "name": path.name, "branches": branches, "head": head, "dirty": dirty}


@app.get("/api/repo/{repo_id}/tree")
def repo_tree(repo_id: str, path: str = ""):
    repo = _repo_or_404(repo_id)
    target = (repo / path) if path else repo
    if not target.exists():
        raise HTTPException(status_code=404, detail="path not found")
    entries = []
    for child in sorted(target.iterdir()):
        if child.name in (".git", "__pycache__", ".pytest_cache") or child.name.startswith(".coverage"):
            continue
        entries.append({"name": child.name, "is_dir": child.is_dir(),
                         "path": str(child.relative_to(repo)).replace("\\", "/")})
    return {"entries": entries}


@app.get("/api/repo/{repo_id}/file")
def repo_file(repo_id: str, path: str, ref: Optional[str] = None):
    repo = _repo_or_404(repo_id)
    if ref:
        result = _git(repo, "show", f"{ref}:{path}")
        if result.returncode != 0:
            raise HTTPException(status_code=404, detail=result.stderr)
        return {"content": result.stdout}
    file_path = repo / path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return {"content": file_path.read_text(encoding="utf-8")}


@app.get("/api/repo/{repo_id}/ledger")
def repo_ledger(repo_id: str):
    repo = _repo_or_404(repo_id)
    ledger, _ = ledger_module.build_ledger(repo, provider=None)
    ledger_module.compute_coverage(repo, ledger)
    return [g.to_dict() for g in ledger]


@app.post("/api/repo/{repo_id}/branch")
def create_branch(repo_id: str, req: CreateBranchRequest):
    repo = _repo_or_404(repo_id)
    result = _git(repo, "checkout", "-q", "-b", req.name, req.from_ref)
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail=result.stderr)
    return {"ok": True, "name": req.name}


@app.put("/api/repo/{repo_id}/file")
def write_file(repo_id: str, req: WriteFileRequest):
    repo = _repo_or_404(repo_id)
    _git(repo, "checkout", "-q", req.branch)
    (repo / req.path).write_text(req.content, encoding="utf-8")
    _git(repo, "add", req.path)
    _git(repo, "commit", "-q", "-m", f"studio: edit {req.path}")
    return {"ok": True}


@app.post("/api/repo/{repo_id}/patch")
def apply_patch_endpoint(repo_id: str, req: ApplyPatchRequest):
    repo = _repo_or_404(repo_id)
    _git(repo, "checkout", "-q", req.branch)
    from engine.fix import apply_patch

    applied, error = apply_patch(repo, req.unified_diff)
    if not applied:
        raise HTTPException(status_code=400, detail=error)
    return {"ok": True}


@app.post("/api/run/premortem")
def start_premortem(req: PremortemRequest):
    repo = _repo_or_404(req.repo_id)
    run_id = uuid.uuid4().hex[:12]
    _run_status[run_id] = "queued"

    def _do():
        return run_premortem(str(repo), req.base, req.head, req.with_, req.fix, req.provider, run_id=run_id)

    threading.Thread(target=lambda: _background_wrapper(run_id, _do), daemon=True).start()
    return {"run_id": run_id}


def _background_wrapper(run_id: str, fn) -> None:
    """`fn` must publish events under `run_id` itself (pass it through to run_premortem/etc.)
    so the client, already subscribed to `run_id`'s stream from the moment this returned, sees
    every event live instead of only getting a filled-in Run object once it's all over."""
    try:
        _run_status[run_id] = "running"
        run = fn()
        _runs[run_id] = run
        _run_status[run_id] = "done"
    except Exception as e:
        _run_status[run_id] = "error"
        events.publish(run_id, "report", "error", {"message": str(e)})


@app.post("/api/run/postmortem")
def start_postmortem(req: PostmortemRequest):
    repo = _repo_or_404(req.repo_id)
    run_id = uuid.uuid4().hex[:12]
    incident_path = req.incident_text or ""

    def _do():
        return run_postmortem(str(repo), incident_path, req.ref, req.provider, run_id=run_id)

    threading.Thread(target=lambda: _background_wrapper(run_id, _do), daemon=True).start()
    return {"run_id": run_id}


@app.get("/api/run/{run_id}/events")
def run_events(run_id: str, from_seq: int = 0):
    def _stream():
        for event in events.subscribe(run_id, from_seq=from_seq):
            yield f"data: {json.dumps(event.to_dict())}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.get("/api/run/{run_id}")
def get_run(run_id: str):
    run = _runs.get(run_id)
    if run is None:
        status = _run_status.get(run_id)
        if status is None:
            raise HTTPException(status_code=404, detail="unknown run_id")
        return {"run_id": run_id, "status": status}
    return run.to_dict()


@app.get("/api/runs")
def list_runs():
    runs_dir = Path("runs")
    if not runs_dir.exists():
        return []
    files = sorted(runs_dir.glob("run-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"run_id": f.stem.removeprefix("run-")} for f in files]


@app.post("/api/run/{run_id}/fix/apply")
def apply_fix(run_id: str):
    run = _runs.get(run_id)
    if run is None or run.fix is None or not run.fix.accepted:
        raise HTTPException(status_code=400, detail="no accepted fix for this run")
    repo = _repo_or_404(list(_repos.keys())[0]) if _repos else None
    if repo is None:
        raise HTTPException(status_code=400, detail="no connected repo")
    from engine.fix import apply_patch

    applied, error = apply_patch(repo, run.fix.unified_diff)
    if not applied:
        raise HTTPException(status_code=400, detail=error)
    return {"ok": True}
