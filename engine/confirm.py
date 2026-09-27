"""The proof gate (§9, M9).

`PROVEN` requires, for premortem: `base == PASS` and `head == FAIL` matching the declared
signature. Rejects, with a named reason, anything that isn't a real, specific, reproducible
proof — measured, never estimated (over-broad is checked by actually running the test against a
control commit, not by guessing that it "looks generic").
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from engine.events import publish
from engine.execute import ExecResult, run_test
from engine.schemas import Candidate, ExpectedFailure, LaneResult


def _matches_expected(result: ExecResult, expected: ExpectedFailure) -> bool:
    if result.status != "FAIL":
        return False
    combined = (result.stdout_tail or "") + (result.stderr_excerpt or "")
    if expected.exception and expected.exception not in combined:
        return False
    if expected.assert_substring and expected.assert_substring not in combined:
        return False
    return True


def _is_tautology(test_code: str, shared_surface: list[str]) -> bool:
    if re.search(r"assert\s+False\b", test_code):
        return True
    if not shared_surface:
        return False
    referenced = any(sym.rsplit(".", 1)[-1] in test_code for sym in shared_surface)
    return not referenced


def confirm_lane(
    lane_id: str, candidate: Candidate, test_path: Path, expected: ExpectedFailure,
    base_wt: Path, head_wt: Path, control_wt: Optional[Path], shared_surface: list[str],
    bus_run_id: Optional[str] = None,
) -> LaneResult:
    test_code = test_path.read_text(encoding="utf-8")

    base_result = run_test(base_wt, test_path, timeout=120)
    if bus_run_id:
        publish(bus_run_id, "race", "lane_base_result", {"lane_id": lane_id, "result": base_result.status})

    if base_result.status == "ERROR":
        return _finish(lane_id, candidate, "INVALID", "errored_on_base",
                        base_result.status, [], expected, bus_run_id,
                        "the probe errored on base — it tested something that doesn't exist there")

    if base_result.touched_app_source:
        return _finish(lane_id, candidate, "INVALID", "touched_app_source",
                        base_result.status, [], expected, bus_run_id, "lane modified application source")

    if base_result.status != "PASS":
        return _finish(lane_id, candidate, "INCONCLUSIVE", "not_executable",
                        base_result.status, [], expected, bus_run_id,
                        f"base did not pass cleanly ({base_result.status}), can't prove a defeat")

    if _is_tautology(test_code, shared_surface):
        return _finish(lane_id, candidate, "DISPROVEN", "tautology",
                        base_result.status, [], expected, bus_run_id,
                        "test never references a shared-surface symbol, or asserts False directly")

    head_runs = []
    last_head_result = None
    for _ in range(3):
        head_result = run_test(head_wt, test_path, timeout=120)
        head_runs.append(head_result.status)
        last_head_result = head_result
        if head_result.touched_app_source:
            return _finish(lane_id, candidate, "INVALID", "touched_app_source",
                            base_result.status, head_runs, expected, bus_run_id,
                            "lane modified application source on head")

    if bus_run_id:
        publish(bus_run_id, "race", "lane_head_result", {"lane_id": lane_id, "results": head_runs})

    if len(set(head_runs)) > 1:
        return _finish(lane_id, candidate, "INCONCLUSIVE", "flaky",
                        base_result.status, head_runs, expected, bus_run_id,
                        f"head result not 3/3 consistent: {head_runs}")

    if all(r == "PASS" for r in head_runs):
        return _finish(lane_id, candidate, "DISPROVEN", None,
                        base_result.status, head_runs, expected, bus_run_id,
                        "head also passes — the claimed defeat doesn't reproduce")

    if not _matches_expected(last_head_result, expected):
        return _finish(lane_id, candidate, "INCONCLUSIVE", "signature_mismatch",
                        base_result.status, head_runs, expected, bus_run_id,
                        "head failed, but not with the declared exception/assertion")

    if control_wt is not None:
        control_result = run_test(control_wt, test_path, timeout=120)
        if control_result.status == "FAIL":
            return _finish(lane_id, candidate, "DISPROVEN", "over_broad",
                            base_result.status, head_runs, expected, bus_run_id,
                            "test also fails against an unrelated control commit — proves nothing "
                            "specific to this merge")

    return _finish(lane_id, candidate, "PROVEN", None,
                    base_result.status, head_runs, expected, bus_run_id,
                    "base PASS, head FAIL 3/3 matching the declared signature")


def _finish(
    lane_id: str, candidate: Candidate, verdict: str, rejection_reason: Optional[str],
    base_result: str, head_runs: list[str], expected: ExpectedFailure,
    bus_run_id: Optional[str], death_note: str,
) -> LaneResult:
    result = LaneResult(
        lane_id=lane_id, candidate_id=candidate.id, test_path="",
        expected_failure=expected, base_result=base_result,
        head_result=head_runs[-1] if head_runs else base_result,
        head_runs=head_runs, verdict=verdict, rejection_reason=rejection_reason,
        death_note=death_note,
    )
    if bus_run_id:
        publish(bus_run_id, "race", "lane_verdict", {"lane_id": lane_id, "verdict": verdict})
    return result
