"""Data contracts for the Witness engine.

Every stage of the pipeline (intake -> blast -> delta -> race -> confirm -> fix -> report)
passes data between processes, across the event bus, and out to `runs/run-<id>.jsonl`, so
every contract here is a plain dataclass with `to_dict`/`from_dict` — nothing that can't
round-trip through JSON.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Optional


def _to_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return {k: _to_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    return obj


class DictMixin:
    """`to_dict`/`from_dict` for dataclasses that are pure JSON-shaped data."""

    def to_dict(self) -> dict:
        return _to_dict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DictMixin":
        field_names = {f.name for f in dataclasses.fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in field_names}
        return cls(**kwargs)


@dataclass
class Guarantee(DictMixin):
    id: str
    statement: str
    why: str
    provenance: list[str]
    enforced_at: list[str] = field(default_factory=list)
    covered_by_test: Optional[str] = None
    surface: list[str] = field(default_factory=list)


@dataclass
class SymbolChange(DictMixin):
    qualname: str
    file: str
    line: int
    kind: str  # function | method | class | module_const
    change: str  # added | removed | signature_changed | body_changed
    old_signature: Optional[str] = None
    new_signature: Optional[str] = None


@dataclass
class StateTouch(DictMixin):
    kind: str  # global | class_attr | module_const | env | sql_table | config_key | cache_key
    name: str
    file: str
    line: int


@dataclass
class ChangeSpec(DictMixin):
    base_ref: str
    head_ref: str
    with_refs: list[str] = field(default_factory=list)
    merge_sha: Optional[str] = None
    textual_conflict: bool = False
    files_changed: list[str] = field(default_factory=list)
    symbols_touched: list[SymbolChange] = field(default_factory=list)
    state_touched: list[StateTouch] = field(default_factory=list)
    introduced_by: dict[str, str] = field(default_factory=dict)
    shared_surface: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = _to_dict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "ChangeSpec":
        data = dict(data)
        data["symbols_touched"] = [
            SymbolChange.from_dict(s) if isinstance(s, dict) else s
            for s in data.get("symbols_touched", [])
        ]
        data["state_touched"] = [
            StateTouch.from_dict(s) if isinstance(s, dict) else s
            for s in data.get("state_touched", [])
        ]
        field_names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in field_names})


@dataclass
class StackFrame(DictMixin):
    file: str
    line: int
    qualname: str


@dataclass
class IncidentSpec(DictMixin):
    title: str
    raw_text: str
    source: str  # issue | pdf | stacktrace | log
    stack_frames: list[StackFrame] = field(default_factory=list)
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    suspect_symbols: list[str] = field(default_factory=list)
    observed_at_ref: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "IncidentSpec":
        data = dict(data)
        data["stack_frames"] = [
            StackFrame.from_dict(s) if isinstance(s, dict) else s
            for s in data.get("stack_frames", [])
        ]
        field_names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in field_names})


@dataclass
class BlastFinding(DictMixin):
    agent: str  # callers | contract | state | history | merge-intent
    subject: str
    claim: str
    evidence: list[str]
    severity_hint: int = 0
    tokens_used: int = 0
    elapsed_s: float = 0.0


@dataclass
class InvariantDelta(DictMixin):
    invariant: str
    held_at_base: bool
    held_at_head: str  # unknown | suspected_broken
    mechanism: str  # bypass | weaken | multiply | reorder | widen | shadow
    unprotected_callers: list[str]
    provenance: list[str]
    rank_score: float
    guarantee_id: Optional[str] = None


@dataclass
class Candidate(DictMixin):
    id: str
    claim: str
    proof_form: str  # differential | contradiction | impossibility
    mechanism: str
    rank_score: float
    delta_ref: str
    guarantee_id: Optional[str] = None


@dataclass
class ExpectedFailure(DictMixin):
    exception: Optional[str]
    assert_substring: str


@dataclass
class LaneResult(DictMixin):
    lane_id: str
    candidate_id: str
    test_path: str
    expected_failure: ExpectedFailure
    head_result: str  # PASS | FAIL | ERROR | TIMEOUT
    verdict: str  # PROVEN | DISPROVEN | INCONCLUSIVE | INVALID
    death_note: str
    base_result: Optional[str] = None
    head_runs: list[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None
    stderr_excerpt: str = ""
    elapsed_s: float = 0.0

    def to_dict(self) -> dict:
        d = _to_dict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "LaneResult":
        data = dict(data)
        ef = data.get("expected_failure")
        if isinstance(ef, dict):
            data["expected_failure"] = ExpectedFailure.from_dict(ef)
        field_names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in field_names})


@dataclass
class FixPatch(DictMixin):
    candidate_id: str
    unified_diff: str
    files_touched: list[str]
    lines_added: int
    lines_removed: int
    suite_before: str
    proof_test_after: str
    suite_after: str
    accepted: bool
    rejection_reason: Optional[str] = None


@dataclass
class Event(DictMixin):
    run_id: str
    seq: int
    ts: float
    stage: str  # intake | blast | delta | race | confirm | fix | report
    kind: str
    payload: dict = field(default_factory=dict)


@dataclass
class Run(DictMixin):
    run_id: str
    mode: str  # premortem | postmortem | standing
    repo: str
    head_ref: str
    base_ref: Optional[str] = None
    with_refs: list[str] = field(default_factory=list)
    change_spec: Optional[ChangeSpec] = None
    incident_spec: Optional[IncidentSpec] = None
    ledger: list[Guarantee] = field(default_factory=list)
    blast: list[BlastFinding] = field(default_factory=list)
    deltas: list[InvariantDelta] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    lanes: list[LaneResult] = field(default_factory=list)
    fix: Optional[FixPatch] = None
    findings: dict = field(default_factory=lambda: {"defeated": [], "undefended": [], "disproven": []})
    metrics: dict = field(default_factory=lambda: {
        "wall_clock_s": 0.0, "lanes_run": 0, "rounds": 0,
        "human_actions": 0, "prompt_tokens": 0, "completion_tokens": 0, "usd_cost": 0.0,
    })

    def to_dict(self) -> dict:
        return _to_dict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Run":
        data = dict(data)
        if data.get("change_spec"):
            data["change_spec"] = ChangeSpec.from_dict(data["change_spec"])
        if data.get("incident_spec"):
            data["incident_spec"] = IncidentSpec.from_dict(data["incident_spec"])
        data["ledger"] = [Guarantee.from_dict(g) if isinstance(g, dict) else g for g in data.get("ledger", [])]
        data["blast"] = [BlastFinding.from_dict(b) if isinstance(b, dict) else b for b in data.get("blast", [])]
        data["deltas"] = [InvariantDelta.from_dict(d) if isinstance(d, dict) else d for d in data.get("deltas", [])]
        data["candidates"] = [Candidate.from_dict(c) if isinstance(c, dict) else c for c in data.get("candidates", [])]
        data["lanes"] = [LaneResult.from_dict(l) if isinstance(l, dict) else l for l in data.get("lanes", [])]
        if data.get("fix"):
            data["fix"] = FixPatch.from_dict(data["fix"])
        field_names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in field_names})
