// Mirrors engine/schemas.py exactly -- do not add fields the backend doesn't send.

export type Verdict = "PROVEN" | "DISPROVEN" | "INCONCLUSIVE" | "INVALID";
export type ExecStatus = "PASS" | "FAIL" | "ERROR" | "TIMEOUT";
export type Mechanism = "bypass" | "weaken" | "multiply" | "reorder" | "widen" | "shadow" | "unknown";

export interface Guarantee {
  id: string;
  statement: string;
  why: string;
  provenance: string[];
  enforced_at: string[];
  covered_by_test: string | null;
  surface: string[];
}

export interface BlastFinding {
  agent: "callers" | "contract" | "state" | "history" | "merge-intent";
  subject: string;
  claim: string;
  evidence: string[];
  severity_hint: number;
  tokens_used: number;
  elapsed_s: number;
}

export interface InvariantDelta {
  guarantee_id: string | null;
  invariant: string;
  held_at_base: boolean;
  held_at_head: string;
  mechanism: Mechanism;
  unprotected_callers: string[];
  provenance: string[];
  rank_score: number;
}

export interface Candidate {
  id: string;
  claim: string;
  guarantee_id: string | null;
  proof_form: string;
  mechanism: string;
  rank_score: number;
  delta_ref: string;
}

export interface ExpectedFailure {
  exception: string | null;
  assert_substring: string;
}

export interface LaneResult {
  lane_id: string;
  candidate_id: string;
  test_path: string;
  expected_failure: ExpectedFailure;
  base_result: ExecStatus | null;
  head_result: ExecStatus;
  head_runs: ExecStatus[];
  verdict: Verdict;
  rejection_reason: string | null;
  stderr_excerpt: string;
  elapsed_s: number;
  death_note: string;
}

export interface FixPatch {
  candidate_id: string;
  unified_diff: string;
  files_touched: string[];
  lines_added: number;
  lines_removed: number;
  suite_before: string;
  proof_test_after: string;
  suite_after: string;
  accepted: boolean;
  rejection_reason: string | null;
}

export interface WitnessEvent {
  run_id: string;
  seq: number;
  ts: number;
  stage: "intake" | "blast" | "delta" | "race" | "confirm" | "fix" | "report";
  kind: string;
  payload: Record<string, unknown>;
}

export interface Run {
  run_id: string;
  mode: "premortem" | "postmortem" | "standing";
  repo: string;
  head_ref: string;
  base_ref: string | null;
  with_refs: string[];
  ledger: Guarantee[];
  blast: BlastFinding[];
  deltas: InvariantDelta[];
  candidates: Candidate[];
  lanes: LaneResult[];
  fix: FixPatch | null;
  findings: { defeated: unknown[]; undefended: string[]; disproven: string[] };
  metrics: {
    wall_clock_s: number;
    lanes_run: number;
    rounds: number;
    human_actions: number;
    prompt_tokens: number;
    completion_tokens: number;
    usd_cost: number;
  };
}

export interface ConnectRepoResponse {
  repo_id: string;
  name: string;
  branches: string[];
  head: string;
  dirty: boolean;
}

export interface TreeEntry {
  name: string;
  is_dir: boolean;
  path: string;
}

export const STAGES = ["intake", "blast", "delta", "race", "confirm", "fix", "report"] as const;
export type Stage = (typeof STAGES)[number];
