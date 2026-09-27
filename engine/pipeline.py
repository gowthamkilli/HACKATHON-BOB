"""Orchestrates intake -> blast -> delta -> race -> confirm -> fix -> report (§4).

Every stage publishes to the event bus as it works — there is no compute-silently-then-render
path. This module is what `engine/cli.py` and `engine/server.py` both call into.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from engine import blast, confirm, delta, intake, ledger as ledger_module, race, worktrees
from engine.events import publish
from engine.llm import get_provider
from engine.schemas import Candidate, Run


def run_premortem(
    repo: str, base: str, head: str, with_refs: Optional[list[str]] = None,
    fix: bool = False, provider_name: str = "watsonx", run_id: Optional[str] = None,
) -> Run:
    repo_path = Path(repo)
    with_refs = with_refs or []
    run_id = run_id or uuid.uuid4().hex[:12]
    provider = get_provider(provider_name)

    run = Run(run_id=run_id, mode="premortem", repo=str(repo_path), head_ref=head,
              base_ref=base, with_refs=with_refs)

    publish(run_id, "intake", "stage_start", {})
    change_spec = intake.build_change_spec(repo_path, base, head, with_refs)
    run.change_spec = change_spec
    publish(run_id, "intake", "stage_end", {"textual_conflict": change_spec.textual_conflict})

    if change_spec.textual_conflict:
        # git already caught this one; Witness adds nothing (§4).
        publish(run_id, "report", "run_end", {"reason": "textual_conflict"})
        return run

    base_wt = worktrees.create(repo_path, base, label=f"run-{run_id}-base")
    merged_wt, merged, conflict = worktrees.create_merge(repo_path, base, [head, *with_refs],
                                                          label=f"run-{run_id}-head")
    try:
        if not merged or conflict:
            publish(run_id, "report", "run_end", {"reason": "merge_failed"})
            return run

        run.ledger, ledger_meta = ledger_module.build_ledger(base_wt, provider=provider)
        ledger_module.compute_coverage(base_wt, run.ledger)

        publish(run_id, "blast", "stage_start", {})
        run.blast = blast.run_blast_radius(change_spec, repo_path, base_wt, merged_wt,
                                            provider=provider, bus_run_id=run_id)
        publish(run_id, "blast", "stage_end", {"count": len(run.blast)})

        publish(run_id, "delta", "stage_start", {})
        raw_deltas = delta.compute_invariant_deltas(run.ledger, change_spec, run.blast)
        run.deltas = delta.rank_deltas(raw_deltas)
        publish(run_id, "delta", "stage_end", {"count": len(run.deltas)})

        by_id = {g.id: g for g in run.ledger}
        run.candidates = [
            Candidate(id=f"c{i}", claim=d.invariant, proof_form="differential",
                      mechanism=d.mechanism, rank_score=d.rank_score,
                      delta_ref=d.guarantee_id or "", guarantee_id=d.guarantee_id)
            for i, d in enumerate(run.deltas)
        ]

        publish(run_id, "race", "stage_start", {})
        control_wt = worktrees.create(repo_path, "main", label=f"run-{run_id}-control")
        try:
            lane_specs = [
                {
                    "lane_id": f"lane-{i}", "candidate": c,
                    "guarantee": by_id.get(c.guarantee_id) if c.guarantee_id else None,
                    "context": {"invariant_delta": d.invariant, "conftest_excerpt": "",
                                "worked_example": ""},
                    "base_wt": base_wt, "head_wt": merged_wt, "control_wt": control_wt,
                    "shared_surface": change_spec.shared_surface, "provider": provider,
                }
                for i, (c, d) in enumerate(zip(run.candidates, run.deltas))
            ]
            run.lanes = race.run_race(lane_specs, bus_run_id=run_id)
        finally:
            worktrees.teardown(control_wt)
        publish(run_id, "race", "stage_end", {"count": len(run.lanes)})

        proven = [l for l in run.lanes if l.verdict == "PROVEN"]

        if fix and proven:
            from engine.fix import attempt_fix
            import tempfile

            top = proven[0]
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
                f.write("# proof test regenerated for fix stage\n")
                proof_path = Path(f.name)
            run.fix = attempt_fix(
                top.candidate_id, proof_path, top.death_note, "",
                "", merged_wt, provider=provider,
            )

        run.findings = {
            "defeated": [{"guarantee_id": l.candidate_id, "test_path": l.test_path,
                          "death_note": l.death_note} for l in proven],
            "undefended": [g.id for g in run.ledger if g.covered_by_test is None],
            "disproven": [l.candidate_id for l in run.lanes if l.verdict == "DISPROVEN"],
        }
        publish(run_id, "report", "run_end", {"defeated": len(proven)})
        return run
    finally:
        worktrees.teardown(base_wt)
        worktrees.teardown(merged_wt)


def run_standing(repo: str, ref: str, provider_name: str = "watsonx", run_id: Optional[str] = None) -> Run:
    repo_path = Path(repo)
    run_id = run_id or uuid.uuid4().hex[:12]
    provider = get_provider(provider_name)
    run = Run(run_id=run_id, mode="standing", repo=str(repo_path), head_ref=ref)

    wt = worktrees.create(repo_path, ref, label=f"standing-{run_id}")
    try:
        run.ledger, _ = ledger_module.build_ledger(wt, provider=provider)
        ledger_module.compute_coverage(wt, run.ledger)
        run.findings = {
            "defeated": [], "disproven": [],
            "undefended": [g.id for g in run.ledger if g.covered_by_test is None],
        }
        publish(run_id, "report", "run_end", {"undefended": len(run.findings["undefended"])})
        return run
    finally:
        worktrees.teardown(wt)


def run_postmortem(repo: str, incident_path: str, ref: str = "HEAD", provider_name: str = "watsonx",
                    run_id: Optional[str] = None) -> Run:
    repo_path = Path(repo)
    run_id = run_id or uuid.uuid4().hex[:12]
    provider = get_provider(provider_name)
    incident_spec = intake.build_incident_spec(incident_path)
    run = Run(run_id=run_id, mode="postmortem", repo=str(repo_path), head_ref=ref,
              incident_spec=incident_spec)
    run.findings = {"defeated": [], "undefended": [], "disproven": []}
    publish(run_id, "report", "run_end", {"note": "postmortem recon agents pending credentials"})
    return run
