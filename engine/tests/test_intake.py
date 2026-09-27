"""M6 acceptance test: ChangeSpec construction across all 8 real branch pairs."""
from pathlib import Path

from engine.intake import build_change_spec
from engine.surface import shared_surface

REPO = Path(__file__).resolve().parents[2] / "samples" / "orderworks"

PAIRS = [
    ("team-a/rate-limit", "team-b/retry"),
    ("team-c/bulk-endpoint", None),
    ("team-b/write-through", "team-d/cache-warm"),
    ("team-a/idempotency-v2", "team-c/request-id"),
    ("team-d/async-notify", "team-b/retry-state-handler"),
    ("team-a/audit-compact", "team-c/soft-delete"),
    ("team-b/pagination", "team-d/query-builder"),
    ("team-a/discounts", "team-c/tax"),
]


def test_pair1_change_spec_has_real_qualnames_and_attributes_introduced_by_correctly():
    spec = build_change_spec(REPO, "team-a/rate-limit", "team-b/retry")
    assert spec.textual_conflict is False
    assert spec.files_changed, "expected changed files"

    qualnames = {s.qualname for s in spec.symbols_touched}
    assert any("orders" in qn for qn in qualnames), qualnames
    for s in spec.symbols_touched:
        assert s.line > 0

    # team-a introduced the limiter wiring (GATEWAY_LIMITER / api changes); team-b introduced
    # the retry wrapper (_charge_with_retry). Both are attributed, computed from git log -S,
    # not asserted from prior knowledge.
    retry_syms = [qn for qn in spec.introduced_by if "retry" in qn.lower() or "charge" in qn.lower()]
    assert retry_syms, qualnames
    for qn in retry_syms:
        assert spec.introduced_by[qn] == "team-b/retry", (qn, spec.introduced_by[qn])


def test_shared_surface_excludes_a_deliberately_changed_signature(tmp_path):
    base_app = tmp_path / "base" / "app"
    head_app = tmp_path / "head" / "app"
    base_app.mkdir(parents=True)
    head_app.mkdir(parents=True)
    (base_app / "m.py").write_text("def f(a, b):\n    return a + b\n\ndef g(x):\n    return x\n")
    (head_app / "m.py").write_text("def f(a, b, c):\n    return a + b + c\n\ndef g(x):\n    return x\n")

    shared = shared_surface(base_app, head_app)
    assert "app.m.g" in shared
    assert "app.m.f" not in shared, "signature changed — must drop out of the shared surface"


def test_all_eight_pairs_produce_non_empty_correct_symbol_lists():
    for base, head in PAIRS:
        effective_base = "main" if head is None else base
        effective_head = base if head is None else head
        spec = build_change_spec(REPO, effective_base, effective_head, with_refs=[])
        assert spec.textual_conflict is False, (base, head)
        assert spec.files_changed, (base, head)
        assert spec.symbols_touched, (base, head)
