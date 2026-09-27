"""M8 acceptance test: invariant delta computation and candidate ranking.

Uses hand-constructed `BlastFinding`s (not a live model) to test the aggregation/ranking
mechanism itself in isolation — the same way M7's concurrency test uses a fake provider. The
spec's own M8 acceptance ("on pair 1 the top-ranked candidate is the G1 ceiling defeat, derived
from the real blast findings" + the rename test) needs a live model's actual merge-intent
judgement first and is deferred — see DECISIONS.md's M8 entry.
"""
from engine.delta import _extract_mechanism, compute_invariant_deltas, rank_deltas
from engine.schemas import BlastFinding, ChangeSpec, Guarantee, SymbolChange


def _make_ledger():
    return [
        Guarantee(id="G1", statement="at most 5 calls/sec reach the gateway", why="cost",
                  provenance=["docs/ADR-001.md:3"], enforced_at=[], surface=["app.gateway.charge"]),
        Guarantee(id="G7", statement="price computed once", why="consistency",
                  provenance=["docs/ADR-007.md:3"], enforced_at=["app/orders.py:33"],
                  surface=["app.orders.create_order"]),
    ]


def _make_change_spec():
    return ChangeSpec(
        base_ref="team-a/rate-limit", head_ref="team-b/retry", with_refs=[],
        symbols_touched=[
            SymbolChange(qualname="app.gateway.charge", file="app/gateway.py", line=10,
                         kind="function", change="body_changed"),
        ],
    )


def test_extract_mechanism_reads_the_models_own_taxonomy_word():
    assert _extract_mechanism("the retry wrapper multiplies gateway calls") == "multiply"
    assert _extract_mechanism("no clear mechanism stated here") == "unknown"


def test_compute_and_rank_deltas_produces_g1_as_top_candidate():
    ledger = _make_ledger()
    change_spec = _make_change_spec()
    findings = [
        BlastFinding(agent="merge-intent", subject="app.gateway.charge",
                     claim="retries multiply real gateway calls past the limiter's ceiling",
                     evidence=["app/api.py:20", "app/orders.py:45"], severity_hint=3),
        BlastFinding(agent="callers", subject="app.gateway.charge",
                     claim="orders.create_order calls charge with no guard",
                     evidence=["app/orders.py:60"], severity_hint=2),
    ]
    deltas = compute_invariant_deltas(ledger, change_spec, findings)
    assert len(deltas) == 1
    assert deltas[0].guarantee_id == "G1"
    assert deltas[0].mechanism == "multiply"

    ranked = rank_deltas(deltas)
    assert ranked[0].guarantee_id == "G1"
    assert ranked[0].rank_score > 0


def test_deltas_with_no_related_findings_are_excluded():
    ledger = _make_ledger()
    change_spec = _make_change_spec()
    deltas = compute_invariant_deltas(ledger, change_spec, blast_findings=[])
    assert deltas == []


def test_rank_deduplicates_to_distinct_guarantees_top_n():
    ledger = _make_ledger()
    from engine.schemas import InvariantDelta

    deltas = [
        InvariantDelta(guarantee_id="G1", invariant="a", held_at_base=True, held_at_head="suspected_broken",
                        mechanism="bypass", unprotected_callers=["x"], provenance=["p:1"], rank_score=0.0),
        InvariantDelta(guarantee_id="G1", invariant="a", held_at_base=True, held_at_head="suspected_broken",
                        mechanism="weaken", unprotected_callers=["y"], provenance=["p:2"], rank_score=0.0),
        InvariantDelta(guarantee_id="G7", invariant="b", held_at_base=True, held_at_head="suspected_broken",
                        mechanism="widen", unprotected_callers=[], provenance=["p:3"], rank_score=0.0),
    ]
    ranked = rank_deltas(deltas)
    guarantee_ids = [d.guarantee_id for d in ranked]
    assert guarantee_ids.count("G1") == 1, "same guarantee proven by two deltas collapses to one"
    assert "G7" in guarantee_ids
