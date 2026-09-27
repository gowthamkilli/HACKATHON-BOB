# DECISIONS

Judgement calls made while executing WITNESS-BUILD-SPEC.md, in order. Append-only.

## First action — Bob 2.0 syntax check

The spec's §12 asks to confirm "IBM Bob 2.0's current subagent, parallel-task and workflow
syntax" against `bob.ibm.com/docs/ide` before writing `engine/prompts/` and a Bob workflow file.
This build runs inside Claude Code, not inside the Bob IDE, and there is no Bob workflow file in
this repo's layout (§6 lists none). The subagent/parallel mechanism actually used here is Claude
Code's own `Agent` tool (PARALLEL milestones spawn concurrent subagents through it) and, inside
the shipped `engine/agents.py`, a plain `ThreadPoolExecutor` over the configured LLM `Provider`.
Nothing in this build depends on Bob-IDE-specific prompt syntax, so this check is recorded as
**not applicable** rather than skipped silently. `engine/prompts/*.md` use a plain
placeholder-substitution grammar (`{{name}}`) documented in `engine/agents.py`'s docstring, not
a Bob-specific format.

## Provider credentials

User selected IBM watsonx.ai as the live provider for this build. Credentials go in the
project's own `.env` (gitignored), keys listed in `.env.example`. `MockProvider` fixtures are
only ever written by an actual `--record` run against that live provider — none are hand-authored.

## M1 — ground truth guarantee provenance (for M4's acceptance test)

| id | statement | ADR provenance | docstring provenance | covered_by_test on main |
|----|-----------|----------------|----------------------|--------------------------|
| G1 | at most 5 calls/sec reach the payment gateway | docs/ADR-001.md:3 | app/gateway.py:3 | no |
| G2 | the same idempotency key creates exactly one order | docs/ADR-002.md:3 | app/orders.py:3 | yes — tests/test_idempotency.py |
| G3 | every order write passes through validate_order() | docs/ADR-003.md:3 | app/orders.py:4 | no |
| G4 | catalog reads are served from cache; DB hit rate < 20% once warm | docs/ADR-004.md:3 | app/cache.py:3 | no |
| G5 | inventory decrement and order insert commit as one transaction | docs/ADR-005.md:3 | app/inventory.py:3 | yes — tests/test_transactions.py |
| G6 | the audit log is append-only; no row is ever updated | docs/ADR-006.md:3 | app/audit.py:3 | no |
| G7 | price is computed once per order, never recomputed downstream | docs/ADR-007.md:3 | app/orders.py:5 | yes — tests/test_pricing.py |
| G8 | notifications fire at most once per order state transition | docs/ADR-008.md:3 | app/orders.py:6 | no |
| G9 | money is integer minor units; no float ever touches a total | docs/ADR-009.md:3 | app/pricing.py:4 | yes — tests/test_money_types.py |
| G10 | list_orders() returns rows sorted by created_at DESC | docs/ADR-010.md:3 | app/orders.py:7 | no |

**Planted self-contradiction 1 (vacuous guard):** `app/orders.py:29` — the branch
`if qty <= 0 and sku == "":` inside `validate_order` is unreachable; `qty <= 0` alone already
raises on line 24.

**Planted self-contradiction 2 (contradicted guarantee):** `app/orders.py:83` —
`find_latest_order_for_customer_sku`'s docstring promises "Never returns None" but the
implementation returns `None` when no matching order exists (line 94).

## M4 — honest coverage result differs from the spec's illustrative M1 table

The spec's M1 table (an illustrative target, not a literal contract) suggested six guarantees
(G1, G3, G4, G6, G8, G10) would end up `covered_by_test: null`. Real `coverage.py` line-coverage
of `enforced_at` — exactly as M4 specifies ("coverage is a measurement, not a guess") — shows
only **G1** is genuinely uncovered: `app/limiter.py` is 0% covered (`RateLimiter` is dormant,
nothing calls it on `main`), confirming G1 has zero enforcement and zero coverage. G2 through
G10 are all covered, because this sample project's test suite is thorough and every one of
their enforcement points (`validate_order`, `get_catalog_item`, `audit.append`, etc.) sits
inside `create_order`/`update_order_state`/`list_orders` — functions nearly every test in the
suite calls as part of its own setup, not just the "dedicated" test for that guarantee.

This was checked, not assumed (`engine/tests/test_ledger.py::test_coverage_based_covered_by_test_is_computed_honestly`
prints the real split), and reported here rather than quietly weakening the test suite to
manufacture artificial gaps just to match the illustrative number — that would be exactly the
kind of engine-tuned-to-the-demo dishonesty §3's Honesty Invariant exists to prevent.

**This does not weaken the deliverable — it points at a stronger claim.** STANDING mode's
"undefended" detection genuinely applies to G1 today. But M2's eight branch-pair defects prove
something the illustrative framing undersells: **four of the eight** (pairs 4, 5, 7, 8) defeat a
guarantee that already *is* `covered_by_test` on its own base branch (G2, G8, G10, G9
respectively) — the existing, passing test suite provides no protection at merge time, because
the new code path the merge introduces isn't the path the existing test exercises. That is the
spec's own central thesis (§1): a covered guarantee is not a protected guarantee. `METRICS.md`
and the M14 write-up report both facts plainly: 1 of 10 guarantees undefended today (G1); 8 of 8
benchmark merges defeat a guarantee regardless of whether it was covered beforehand.

## M5 — credentials still pending

`engine/llm.py` (Provider protocol + Watsonx/Anthropic/OpenAI/Mock) and `engine/agents.py`
(subagent harness) are built and real — built ahead of their milestone number, during M4, because
M4's ledger model-pass genuinely depends on this mechanism (recorded above). `engine/tests/test_agents.py`
verifies concurrency (5 fake-but-real-latency agents run in parallel, under 1.6x one agent's
delay — proves `ThreadPoolExecutor`, not a loop), the retry-once-then-`ok=False` contract, and
`MockProvider`'s honest fixture-or-`FixtureMissing` behavior — all with no credentials needed.
Two spec-listed checks that need a real model account are `pytest.mark.skipif`-guarded with the
exact reason (`test_live_watsonx_call_returns_parseable_block`,
`test_mock_replay_matches_live_recording_byte_identical`) rather than faked. Once
`WATSONX_API_KEY`/`WATSONX_PROJECT_ID` land in `.env`, run:
`python -m pytest engine/tests/test_agents.py -v` — the two skips should turn into real passes,
and `--record` against a live call will populate `engine/fixtures/` honestly.

## M2 — branch pair 1 (G1, multiply): team-a/rate-limit + team-b/retry

- `main` = `42b345d`, `team-a/rate-limit` = `cb87c6d`, `team-b/retry` = `2c39687`.
- team-a wires `RateLimiter(5/sec)` into `POST /orders` at the HTTP layer (`app/api.py`),
  reasoning "1 request = 1 gateway call."
- team-b, independently, adds retry-with-backoff around `gateway.charge()` inside
  `orders.create_order` (`app/orders.py`) for transient timeouts.
- Merge (`git merge --no-commit --no-ff`): zero textual conflict, confirmed by hand.
- Full suite green at merge (24 passed).
- Ground-truth throwaway test (`tests/_ground_truth_g1.py`, never committed): 5 order requests,
  vendor forced to always time out. Base (team-a alone): 5 vendor calls (1/request, no retry) —
  assertion `len(calls) <= 5` **passes**. Head (merged): 15 vendor calls (3/request via retry) —
  same assertion **fails** (`15 <= 5` is False). Confirms the limiter counts HTTP requests, not
  actual vendor calls, so retries multiply real gateway traffic past the ceiling it never sees.

## M2 — branch pair 2 (G3, bypass): team-c/bulk-endpoint (alone)

- `main` = `42b345d`, `team-c/bulk-endpoint` = `28a8cb8` (single branch, per spec table row 2).
- `orders.bulk_insert_orders` + `POST /orders/bulk` write order rows directly for a "trusted
  partner feed," skipping `validate_order()` entirely.
- Suite green alone (22 passed).
- Ground-truth test (`_ground_truth_g3.py`, never committed): POST a qty=-1 row to
  `/orders/bulk`. Base (main): route 404s, 0 invalid rows — **passes**. Head
  (team-c/bulk-endpoint): route inserts it directly, 1 invalid row lands — **fails**
  (`1 == 0` false).

## M2 — branch pair 3 (G4, shadow): team-b/write-through + team-d/cache-warm

- `main` = `42b345d`, `team-b/write-through` = broadens `cache.invalidate` to clear the whole
  store on any write; own test only checks same-sku freshness, not cross-sku impact.
  `team-d/cache-warm` = adds `cache.warm_cache()`, independent, own test only checks warming.
- Merge: `git merge --no-commit --no-ff` — one file (`app/cache.py`) auto-merged with zero
  conflict (edits landed on different lines/functions). Full suite green after merge (23 passed).
- **Judgment call:** team-b/write-through's global-clear is, mechanically, already active on
  that branch alone (not gated behind team-d's code) — so the ground-truth test's "base" is
  `main` rather than `team-b/write-through` alone; team-b's OWN test suite still passes on that
  branch alone because it never checks a second, unrelated sku. Recorded here rather than
  silently treated as a clean two-branch-only interaction.
- Ground-truth test (`_ground_truth_g4.py`, never committed): warm WIDGET, place 10 unrelated
  GADGET orders, check WIDGET is still in the cache store. Base (main): per-sku invalidation
  never touches WIDGET — **passes**. Head (merged): the whole-cache clear evicts WIDGET on the
  very first GADGET write — **fails** (`'WIDGET' in {}`).

## M2 — branch pair 4 (G2, widen): team-a/idempotency-v2 + team-c/request-id

- `main` = `42b345d`. team-a/idempotency-v2: `create_order` derives a stable idempotency key
  from (customer_id, sku, minute) when the caller passes none. team-c/request-id, independently:
  `api.py` always generates a fresh `uuid4()` request_id when the client omits one, "for tracing."
- Both branches green alone on their own suites; team-a's branch required updating
  `tests/test_listing.py` to pass explicit distinct keys (a real consequence of the v2 behavior
  change, not a hidden defect).
- Merge: zero textual conflict (`app/api.py` vs `app/orders.py`, different files). Full suite
  green after merge (25 passed).
- Ground-truth test (`_ground_truth_g2.py`, never committed): the same POST /orders body sent
  twice (a simulated client retry), no explicit key. Base (team-a alone): idempotency_key=None
  reaches `create_order`, which derives a stable key — **passes** (one order). Head (merged):
  `api.py` now always supplies a fresh uuid before `create_order` ever sees `None` — **fails**
  (`1 == 2`, two orders created for one logical retry).

## M2 — branch pair 5 (G8, multiply): team-d/async-notify + team-b/retry-state-handler

- `main` = `42b345d`. team-d/async-notify: `update_order_state` now also calls
  `notify.record_delivery()` (a new sqlite write) after sending the notification, for an async
  delivery dashboard. team-b/retry-state-handler, independently: wraps the whole
  `PATCH /orders/{id}/state` route in a generic `retry_on_operational_error` decorator
  (`app/retry.py`), for transient sqlite lock errors.
- Both green alone (22 and 24 passed respectively).
- Merge: zero textual conflict. Full suite green after merge (25 passed).
- Ground-truth test (`_ground_truth_g8.py`, never committed): force
  `notify.record_delivery`'s first call to raise `sqlite3.OperationalError`, then PATCH a state
  change once. Base (team-d alone): no retry — the handler just fails, notification sent once —
  **passes**. Head (merged): the retry wrapper re-runs the whole handler, re-sending the
  notification before `record_delivery` succeeds on the 2nd attempt — **fails** (2 sent, not 1).

## M2 — branch pair 6 (G6, bypass): team-a/audit-compact + team-c/soft-delete

- `main` = `42b345d`. team-a/audit-compact: `audit.append()` now auto-triggers
  `compact_audit_log()` every `COMPACT_THRESHOLD=50` rows, merging the oldest 10 rows into one
  `UPDATE` + 9 `DELETE`s, regardless of which order/action produced the volume. team-c/soft-delete,
  independently: `orders.soft_delete_order()` marks an order deleted and appends a `soft_delete`
  audit row, keeping the trail intact by design.
- Both green alone (22 passed each). Merge: zero textual conflict, full suite green (23 passed).
- **Judgment call (same pattern as pair 3):** compaction fires from raw row-count regardless of
  branch, so it is already "live" on team-a/audit-compact alone — the ground-truth test's "base"
  is `main`. team-c/soft-delete is the realistic production trigger for that volume and the
  concrete record type (a soft-deleted order's own trail) a compliance audit would query, even
  though the differential proof itself (`_ground_truth_g6.py`, never committed, uses only
  shared-surface calls so the same file runs on both refs) demonstrates the underlying
  UPDATE-on-an-audit-row mechanism directly: 30 orders created + transitioned (60 audit rows,
  crossing the threshold). Base (main): no compaction — order 1's rows are untouched — **passes**.
  Head (merged): order 1's rows got merged into a `compacted` summary row — **fails**.

## M2 — branch pair 7 (G10, reorder): team-b/pagination + team-d/query-builder

- `main` = `42b345d`. team-b/pagination: adds `orders.list_orders_page(page, page_size)`, a
  convenience wrapper over the existing `list_orders`. team-d/query-builder, independently:
  adds `api._dedupe_by_id()` to `GET /orders`, ahead of a planned customer-enrichment join that
  can produce duplicate rows — sorts by `id` for deterministic dedup output.
- Both green alone (22 passed each). Merge: zero textual conflict (`app/orders.py` vs
  `app/api.py`). Full suite green after merge (23 passed).
- Ground-truth test (`_ground_truth_g10.py`, never committed): create 3 orders, GET /orders.
  Base (team-b/pagination alone): response is `list_orders`'s own DESC-by-created_at order —
  **passes**. Head (merged): `_dedupe_by_id`'s `sorted(..., key=id)` replaces that ordering with
  ascending id — **fails** (`[1,2,3] != [3,2,1]`).

## M2 — branch pair 8 (G9, weaken): team-a/discounts + team-c/tax

- `main` = `42b345d`. team-a/discounts: `pricing.apply_loyalty_discount()`, correct
  (`round()`, no ndigits → always int), stacked in `create_order` via a new `loyalty_tier` param.
  team-c/tax, independently: `pricing.apply_tax()`, wired unconditionally into every order's
  total — uses `round(x, 2)` (WITH an `ndigits` argument), which **always returns `float`** in
  Python, even when the value is numerically a whole number of cents.
- **First merge attempt conflicted** (both branches inserted their new function/call at the same
  anchor point in `pricing.py` and `orders.py`). Fixed by repositioning team-c's addition
  (`refactor(pricing): apply tax before discount...`, `7f7a412`) to a non-overlapping location —
  recorded here rather than silently retried, since the spec requires the 8 pairs to be
  zero-conflict by construction, not by luck.
- team-c wiring tax into every order's total broke the *existing* `test_pricing.py` /
  `test_money_types.py` assertions (which predate tax); updated them on team-c/tax's own branch
  to the taxed value, same pattern used for team-a/idempotency-v2 (pair 4) and team-a/discounts
  itself needed a second fix — its own loyalty test asserted an absolute total that tax would
  have broken at merge, so it was rewritten as a relative (95%-of-plain) check before the merge
  was retried. Both fixes are ordinary "a real behavior change requires updating the tests it
  affects" work, not defect concealment.
- Both branches green alone (23 passed each after fixes). Merge: zero conflict on retry, full
  suite green (25 passed).
- **Judgment call (same pattern as pairs 3 & 6):** the float leak is entirely team-c/tax's own
  bug (`round(x, 2)`), inert without team-a. Ground-truth test (`_ground_truth_g9.py`, never
  committed) feature-detects `pricing.apply_tax`: absent → trivially passes; present → asserts
  `isinstance(apply_tax(...), int)`. Base (team-a/discounts alone): function absent — **passes**.
  Head (merged): function present, `round(1080.0, 2)` is `float` — **fails**.

## M1 — sample project author identities

`git commit --author` is used with four synthetic identities (team-a/b/c/d @ orderworks.local)
to satisfy "4 notional team identities" — these are fictional commit authors inside the sample
project's own throwaway repo, not real people, and are clearly not the outer Witness repo's
authorship.
