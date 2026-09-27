"""M3 acceptance test: the differential execution harness, proved against the real corpus."""
from pathlib import Path

import pytest

from engine import worktrees
from engine.execute import run_test
from engine.worktrees import _snapshot

REPO = Path(__file__).resolve().parents[2] / "samples" / "orderworks"

G1_PROOF_TEST = '''
"""Hand-written proof test for G1 (ADR-001): at most 5 calls/sec reach the payment gateway."""
import importlib
from fastapi.testclient import TestClient
from app import gateway


def test_g1_ceiling_holds(monkeypatch, tmp_path):
    db_path = str(tmp_path / "g1.db")
    from app import db as db_module
    db_module.reset(db_path)
    from app import inventory
    inventory.upsert_item(db_path, "WIDGET", qty_on_hand=100, unit_price_cents=500)

    monkeypatch.setenv("ORDERWORKS_DB", db_path)
    from app import api as api_module
    importlib.reload(api_module)
    api_module.DB_PATH = db_path

    gateway.reset_call_log()
    gateway.set_fault_injector(lambda: True)
    client = TestClient(api_module.app, raise_server_exceptions=False)
    for i in range(5):
        client.post("/orders", json={"customer_id": "cust-1", "sku": "WIDGET", "qty": 1,
                                      "idempotency_key": f"gt-{i}"})
    calls = gateway.call_log_snapshot()
    assert len(calls) <= 5, f"expected at most 5 vendor calls/sec, got {len(calls)}"
'''

IMPORT_ERROR_TEST = '''
import this_module_does_not_exist_anywhere  # noqa

def test_never_runs():
    assert True
'''

HANG_TEST = '''
def test_hangs_forever():
    while True:
        pass
'''


@pytest.fixture
def scratch_file(tmp_path):
    def _write(name: str, content: str) -> Path:
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p
    return _write


def test_main_tree_untouched_across_all_three_probes(scratch_file):
    before = _snapshot(REPO)

    _run_g1_differential(scratch_file)
    _run_import_error_probe(scratch_file)
    _run_hang_probe(scratch_file)

    worktrees.assert_main_tree_untouched(REPO, before)


def _run_g1_differential(scratch_file):
    test_path = scratch_file("test_g1_proof.py", G1_PROOF_TEST)

    base_wt = worktrees.create(REPO, "team-a/rate-limit", label="m3-g1-base")
    try:
        base_result = run_test(base_wt, test_path, timeout=30)
    finally:
        worktrees.teardown(base_wt)
    assert base_result.status == "PASS", base_result.stderr_excerpt

    head_wt, merged, conflict = worktrees.create_merge(
        REPO, "team-a/rate-limit", ["team-b/retry"], label="m3-g1-head"
    )
    try:
        assert merged and not conflict
        head_result = run_test(head_wt, test_path, timeout=30)
    finally:
        worktrees.teardown(head_wt)
    assert head_result.status == "FAIL", head_result.stdout_tail


def _run_import_error_probe(scratch_file):
    test_path = scratch_file("test_import_error.py", IMPORT_ERROR_TEST)
    wt = worktrees.create(REPO, "main", label="m3-error-probe")
    try:
        result = run_test(wt, test_path, timeout=30)
    finally:
        worktrees.teardown(wt)
    assert result.status == "ERROR", f"expected ERROR (never FAIL) for an import error, got {result.status}"


def _run_hang_probe(scratch_file):
    test_path = scratch_file("test_hang.py", HANG_TEST)
    wt = worktrees.create(REPO, "main", label="m3-hang-probe")
    try:
        result = run_test(wt, test_path, timeout=3)
    finally:
        worktrees.teardown(wt)
    assert result.status == "TIMEOUT"
