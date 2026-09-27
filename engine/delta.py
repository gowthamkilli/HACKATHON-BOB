"""Invariant delta and candidate ranking (§9, M8).

`old_guarantees ⊖ new_guarantees`: ledger entries whose `surface` intersects the change's
touched symbols are the ones at risk. Each becomes an `InvariantDelta`, joined with whatever the
blast-radius agents found about it, and ranked.

**Mechanism classification is the model's judgement, not the engine's guess.** The six-word
taxonomy (bypass/weaken/multiply/reorder/widen/shadow) is the spec's own classification
vocabulary (§4) that `merge-intent.md` instructs the model to name in its claim — this module
only extracts which of those six spec-defined words the model actually used. It never infers a
mechanism from case-specific keywords (there are none here — see `test_no_case_specific_logic.py`).
"""
from __future__ import annotations

import re
from typing import Optional

from engine.schemas import BlastFinding, ChangeSpec, Guarantee, InvariantDelta

_MECHANISM_WEIGHTS = {
    "bypass": 1.0, "multiply": 0.9, "weaken": 0.8,
    "reorder": 0.7, "widen": 0.6, "shadow": 0.5, "unknown": 0.4,
}
_MECHANISM_STEMS = {
    "bypass": "bypass", "weaken": "weaken", "multipl": "multiply",
    "reorder": "reorder", "widen": "widen", "shadow": "shadow",
}
_MECHANISM_WORDS = re.compile(
    r"\b(bypass|weaken|multipl|reorder|widen|shadow)\w*\b", re.IGNORECASE
)


def _extract_mechanism(claim: str) -> str:
    """Matches on word stems (e.g. "multipl" catches multiply/multiplies/multiplying) since a
    model's natural-language claim will inflect the spec's six taxonomy words."""
    m = _MECHANISM_WORDS.search(claim)
    return _MECHANISM_STEMS[m.group(1).lower()] if m else "unknown"


def compute_invariant_deltas(
    ledger: list[Guarantee], change_spec: ChangeSpec, blast_findings: list[BlastFinding],
) -> list[InvariantDelta]:
    touched = {s.qualname for s in change_spec.symbols_touched}
    at_risk = [g for g in ledger if touched & set(g.surface)]

    findings_by_subject: dict[str, list[BlastFinding]] = {}
    for f in blast_findings:
        findings_by_subject.setdefault(f.subject, []).append(f)

    deltas: list[InvariantDelta] = []
    for g in at_risk:
        related = []
        for surface_qn in g.surface:
            related.extend(findings_by_subject.get(surface_qn, []))
        # A finding whose subject is the guarantee id itself (a model may cite "G1" as subject,
        # since guarantee ids are data read from the ledger, not code) also counts.
        related.extend(findings_by_subject.get(g.id, []))

        if not related:
            continue

        merge_intent = [f for f in related if f.agent == "merge-intent"]
        primary = merge_intent[0] if merge_intent else related[0]
        mechanism = _extract_mechanism(primary.claim)

        unprotected = [f.subject for f in related if f.agent == "callers"]
        provenance = sorted({e for f in related for e in f.evidence} | set(g.provenance))

        deltas.append(InvariantDelta(
            guarantee_id=g.id,
            invariant=g.statement,
            held_at_base=True,
            held_at_head="suspected_broken",
            mechanism=mechanism,
            unprotected_callers=unprotected,
            provenance=list(provenance),
            rank_score=0.0,  # filled in by rank_candidates
        ))
    return deltas


def rank_deltas(deltas: list[InvariantDelta]) -> list[InvariantDelta]:
    """PREMORTEM rank = unprotected_callers x mechanism_weight x (1.0 if uncovered else 0.3)."""
    ranked = []
    for d in deltas:
        if not d.provenance:
            continue  # a candidate with empty provenance is dropped before the race
        weight = _MECHANISM_WEIGHTS.get(d.mechanism, _MECHANISM_WEIGHTS["unknown"])
        caller_factor = max(len(d.unprotected_callers), 1)
        coverage_factor = 1.0 if d.held_at_head == "suspected_broken" else 0.3
        d.rank_score = caller_factor * weight * coverage_factor
        ranked.append(d)
    ranked.sort(key=lambda d: d.rank_score, reverse=True)
    return _dedupe_top_n(ranked, n=5)


def _dedupe_top_n(ranked: list[InvariantDelta], n: int) -> list[InvariantDelta]:
    """Two deltas that would be proven by the same test collapse into one; the next distinct
    one is promoted, up to `n` total."""
    seen_guarantees: set[Optional[str]] = set()
    result = []
    for d in ranked:
        if d.guarantee_id in seen_guarantees:
            continue
        seen_guarantees.add(d.guarantee_id)
        result.append(d)
        if len(result) >= n:
            break
    return result
