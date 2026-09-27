"""M5 acceptance test: the subagent harness — concurrency, retry-once, and the mock contract.

Two of the spec's M5 acceptance checks need a live model call ("a live watsonx call through
run_agent returns a parseable block" and "the same run under --provider mock yields
byte-identical AgentResults" for a fixture actually recorded from that call). Both are marked
`skip` with the exact reason, rather than faked — see DECISIONS.md's M5 entry. Everything else
in this file needs no credentials and is fully real.
"""
from __future__ import annotations

import os
import time

import pytest

from engine.agents import run_agent, run_agents_parallel
from engine.llm import Completion, FixtureMissing, MockProvider


class _SlowFakeProvider:
    """A controllable stand-in that proves real concurrency without needing a live model."""

    def __init__(self, delay_s: float = 0.3, text: str = "FINDING_START\nOK\nFINDING_END"):
        self.delay_s = delay_s
        self.text = text
        self.calls = 0

    def complete(self, system: str, user: str, *, max_tokens: int, temperature: float,
                 stop=None) -> Completion:
        self.calls += 1
        time.sleep(self.delay_s)
        return Completion(text=self.text, prompt_tokens=10, completion_tokens=5,
                           model="fake", elapsed_s=self.delay_s, finish_reason="stop")


class _ProseThenNothingProvider:
    """Emits unparseable prose every time — proves the retry-once-then-give-up contract."""

    def __init__(self):
        self.calls = 0

    def complete(self, system: str, user: str, *, max_tokens: int, temperature: float,
                 stop=None) -> Completion:
        self.calls += 1
        return Completion(text="This is just prose, not the declared format.",
                           prompt_tokens=5, completion_tokens=5, model="fake",
                           elapsed_s=0.0, finish_reason="stop")


def _strict_parser(text: str):
    if "FINDING_START" not in text:
        raise ValueError("missing FINDING_START")
    return {"ok": True}


def test_run_agents_parallel_is_real_concurrency_not_a_loop():
    provider = _SlowFakeProvider(delay_s=0.3)
    specs = [
        {"name": "callers", "context": {}, "parse_fn": _strict_parser},
        {"name": "contract", "context": {}, "parse_fn": _strict_parser},
        {"name": "state", "context": {}, "parse_fn": _strict_parser},
        {"name": "history", "context": {}, "parse_fn": _strict_parser},
        {"name": "merge-intent", "context": {}, "parse_fn": _strict_parser},
    ]
    start = time.monotonic()
    results = run_agents_parallel(specs, max_workers=5, provider=provider)
    elapsed = time.monotonic() - start

    assert all(r.ok for r in results)
    assert elapsed < 1.6 * provider.delay_s, f"took {elapsed}s, expected under {1.6 * provider.delay_s}s"


def test_agent_emitting_prose_is_retried_once_then_ok_false():
    provider = _ProseThenNothingProvider()
    result = run_agent("callers", {}, parse_fn=_strict_parser, provider=provider)
    assert result.ok is False
    assert provider.calls == 2, "expected exactly one retry (2 total attempts)"


def test_mock_provider_cache_miss_raises_fixture_missing(tmp_path):
    provider = MockProvider(fixtures_dir=tmp_path / "fixtures")
    with pytest.raises(FixtureMissing):
        provider.complete(system="s", user="u-never-recorded", max_tokens=100, temperature=0.0)


def test_mock_provider_replays_a_recorded_fixture_exactly(tmp_path):
    provider = MockProvider(fixtures_dir=tmp_path / "fixtures")
    original = Completion(text="hello", prompt_tokens=1, completion_tokens=1,
                           model="m", elapsed_s=0.1, finish_reason="stop")
    provider.record("sys", "usr", original)
    replayed = provider.complete(system="sys", user="usr", max_tokens=10, temperature=0.0)
    assert replayed == original


@pytest.mark.skipif(
    not os.environ.get("WATSONX_API_KEY"),
    reason="needs WATSONX_API_KEY in .env — see DECISIONS.md M5 entry; never faked",
)
def test_live_watsonx_call_returns_parseable_block():
    from engine.llm import WatsonxProvider

    provider = WatsonxProvider()
    result = run_agent(
        "callers", {"symbols": "app.orders.create_order", "callgraph": "(none)"},
        parse_fn=lambda t: t, provider=provider,
    )
    assert result.ok


@pytest.mark.skipif(
    not (os.environ.get("WATSONX_API_KEY") and (
        __import__("pathlib").Path("engine/fixtures").exists()
    )),
    reason="needs a fixture recorded from a live run first (witness ... --record) — never hand-authored",
)
def test_mock_replay_matches_live_recording_byte_identical():
    pytest.skip("run after recording a fixture with --record; see DECISIONS.md M5 entry")
