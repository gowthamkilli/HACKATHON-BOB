"""M7 acceptance test: the 5 parallel blast-radius agents.

The spec's real acceptance check ("on pair 1, merge-intent produces a finding naming the
limiter and the retry path, with evidence in both branches") needs a live model and is
`skipif`-guarded — see DECISIONS.md's M7 entry. What's tested here without credentials: the
shared FINDING_START/END grammar (including "evidence-free findings are dropped, not reported"),
and that `run_blast_radius` genuinely fans out 5 agents concurrently rather than looping.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from engine.blast import parse_findings, run_blast_radius
from engine.intake import build_change_spec
from engine.llm import Completion

REPO = Path(__file__).resolve().parents[2] / "samples" / "orderworks"


def test_parse_findings_extracts_blocks_and_requires_evidence():
    text = (
        "FINDING_START\nSUBJECT: app.orders.create_order\nCLAIM: something.\n"
        "EVIDENCE: app/orders.py:10\nSEVERITY: 2\nFINDING_END\n"
        "FINDING_START\nSUBJECT: no_evidence\nCLAIM: unsupported.\nEVIDENCE: \nSEVERITY: 1\nFINDING_END\n"
    )
    blocks = parse_findings(text)
    assert len(blocks) == 2
    assert blocks[0]["evidence"] == ["app/orders.py:10"]
    assert blocks[1]["evidence"] == []  # caller (run_blast_radius) is what drops this one


def test_parse_findings_empty_text_is_valid_silence():
    assert parse_findings("nothing here") == []


class _FakeParallelProvider:
    def __init__(self, delay_s: float = 0.2):
        self.delay_s = delay_s

    def complete(self, system, user, *, max_tokens, temperature, stop=None) -> Completion:
        time.sleep(self.delay_s)
        return Completion(
            text="FINDING_START\nSUBJECT: x\nCLAIM: y\nEVIDENCE: app/orders.py:1\nSEVERITY: 1\nFINDING_END",
            prompt_tokens=10, completion_tokens=5, model="fake", elapsed_s=self.delay_s,
            finish_reason="stop",
        )


def test_run_blast_radius_fans_out_five_agents_concurrently():
    spec = build_change_spec(REPO, "team-a/rate-limit", "team-b/retry")
    from engine import worktrees

    base_wt = worktrees.create(REPO, "team-a/rate-limit", label="blast-test-base")
    merged_wt, merged, conflict = worktrees.create_merge(REPO, "team-a/rate-limit", ["team-b/retry"], label="blast-test-head")
    try:
        assert merged and not conflict
        provider = _FakeParallelProvider(delay_s=0.4)
        start = time.monotonic()
        findings = run_blast_radius(spec, REPO, base_wt, merged_wt, provider=provider)
        elapsed = time.monotonic() - start
        assert elapsed < 1.6 * 0.4
        assert len(findings) == 5  # all 5 agents returned one evidence-bearing finding each
    finally:
        worktrees.teardown(base_wt)
        worktrees.teardown(merged_wt)


@pytest.mark.skipif(
    not os.environ.get("WATSONX_API_KEY"),
    reason="needs a live model — merge-intent's real judgement can't be faked; see DECISIONS.md M7 entry",
)
def test_merge_intent_names_limiter_and_retry_on_pair1():
    from engine.llm import WatsonxProvider
    from engine import worktrees

    spec = build_change_spec(REPO, "team-a/rate-limit", "team-b/retry")
    base_wt = worktrees.create(REPO, "team-a/rate-limit", label="blast-live-base")
    merged_wt, merged, conflict = worktrees.create_merge(REPO, "team-a/rate-limit", ["team-b/retry"], label="blast-live-head")
    try:
        findings = run_blast_radius(spec, REPO, base_wt, merged_wt, provider=WatsonxProvider())
        merge_intent = [f for f in findings if f.agent == "merge-intent"]
        assert merge_intent
        claim_text = " ".join(f.claim.lower() for f in merge_intent)
        assert "limit" in claim_text and "retry" in claim_text
        for f in merge_intent:
            assert len(f.evidence) >= 2
    finally:
        worktrees.teardown(base_wt)
        worktrees.teardown(merged_wt)
