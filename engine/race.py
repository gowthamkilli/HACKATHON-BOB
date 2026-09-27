"""The race — 5 lane subagents, concurrent, one candidate each (§9, M9).

Every lane MUST emit an executable test file; prose is a lost lane, full stop. Lanes stream:
each publishes `lane_start`, `lane_test_written`, `lane_base_result`, `lane_head_result`,
`lane_verdict` as they happen, so a lane that finishes in 4s shows its verdict at 4s, not when
the round ends.
"""
from __future__ import annotations

import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from engine.confirm import confirm_lane
from engine.events import publish
from engine.execute import run_test
from engine.llm import Provider
from engine.schemas import Candidate, ExpectedFailure, Guarantee, LaneResult

_TEST_FILE_RE = re.compile(r"TEST_FILE_START(.*?)TEST_FILE_END", re.DOTALL)


class LaneGenerationError(Exception):
    pass


def parse_lane_response(text: str) -> dict:
    match = _TEST_FILE_RE.search(text)
    if not match:
        raise LaneGenerationError("no TEST_FILE_START/TEST_FILE_END block — prose is a lost lane")
    test_code = match.group(1).strip("\n")
    if not test_code.strip():
        raise LaneGenerationError("empty test file")

    exc_match = re.search(r"EXPECTED_EXCEPTION:[ \t]*(\S+)", text)
    assert_match = re.search(r"EXPECTED_ASSERT_SUBSTRING:[ \t]*(.*)", text)
    exception = exc_match.group(1).strip() if exc_match else "NONE"
    assert_substring = assert_match.group(1).strip() if assert_match else "NONE"

    return {
        "test_code": test_code,
        "expected_exception": None if exception.upper() == "NONE" else exception,
        "expected_assert_substring": "" if assert_substring.upper() == "NONE" else assert_substring,
    }


def run_lane(
    lane_id: str, candidate: Candidate, guarantee: Optional[Guarantee], context: dict, *,
    base_wt: Path, head_wt: Path, control_wt: Optional[Path], shared_surface: list[str],
    provider: Provider, bus_run_id: Optional[str] = None,
) -> LaneResult:
    if bus_run_id:
        publish(bus_run_id, "race", "lane_start", {"lane_id": lane_id, "candidate_id": candidate.id})

    rendered_context = {
        "shared_surface": "\n".join(shared_surface),
        "claim": candidate.claim,
        "guarantee_statement": guarantee.statement if guarantee else candidate.claim,
        "guarantee_why": guarantee.why if guarantee else "",
        "guarantee_provenance": ", ".join(guarantee.provenance) if guarantee else "",
        "invariant_delta": context.get("invariant_delta", ""),
        "conftest_excerpt": context.get("conftest_excerpt", ""),
        "worked_example": context.get("worked_example", ""),
    }

    from engine.agents import run_agent

    result = run_agent("lane", rendered_context, parse_fn=parse_lane_response, provider=provider,
                        bus_run_id=bus_run_id, stage="race", max_tokens=1500)

    death_note = ""
    if not result.ok:
        death_note = f"lane generation failed: {result.error}"
        lane_result = LaneResult(
            lane_id=lane_id, candidate_id=candidate.id, test_path="",
            expected_failure=ExpectedFailure(exception=None, assert_substring=""),
            head_result="ERROR", verdict="INVALID", death_note=death_note,
            rejection_reason="not_executable",
        )
        if bus_run_id:
            publish(bus_run_id, "race", "lane_verdict", {"lane_id": lane_id, "verdict": "INVALID"})
        return lane_result

    parsed = result.parsed
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(parsed["test_code"])
        test_path = Path(f.name)

    if bus_run_id:
        publish(bus_run_id, "race", "lane_test_written", {"lane_id": lane_id, "test_path": str(test_path)})

    expected = ExpectedFailure(
        exception=parsed["expected_exception"], assert_substring=parsed["expected_assert_substring"],
    )

    lane_result = confirm_lane(
        lane_id=lane_id, candidate=candidate, test_path=test_path, expected=expected,
        base_wt=base_wt, head_wt=head_wt, control_wt=control_wt, shared_surface=shared_surface,
        bus_run_id=bus_run_id,
    )
    return lane_result


def run_race(
    lanes: list[dict], *, max_workers: int = 5, bus_run_id: Optional[str] = None,
) -> list[LaneResult]:
    """Each lane dict: {lane_id, candidate, guarantee, context, base_wt, head_wt, control_wt,
    shared_surface, provider}."""

    def _one(lane: dict) -> LaneResult:
        return run_lane(
            lane["lane_id"], lane["candidate"], lane.get("guarantee"), lane.get("context", {}),
            base_wt=lane["base_wt"], head_wt=lane["head_wt"], control_wt=lane.get("control_wt"),
            shared_surface=lane["shared_surface"], provider=lane["provider"], bus_run_id=bus_run_id,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(_one, lanes))
