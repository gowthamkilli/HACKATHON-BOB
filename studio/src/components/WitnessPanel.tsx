import { useState } from "react";
import { api } from "../api/client";
import type { AgentMode } from "./Composer";
import Composer from "./Composer";
import FindingCard from "./FindingCard";
import FixDiff from "./FixDiff";
import LaneCard from "./LaneCard";
import LedgerTable from "./LedgerTable";
import StageList from "./StageList";
import TokenMeter from "./TokenMeter";
import AgentRow from "./AgentRow";
import { useWitness } from "../state/store";

const BLAST_AGENTS = ["callers", "contract", "state", "history", "merge-intent"];

interface WitnessPanelProps {
  repoId: string | null;
  base: string;
  branches: string[];
  onStartRun: (runId: string, isReplay: boolean) => void;
  onProvenanceClick: (site: string) => void;
}

export default function WitnessPanel({ repoId, base, branches, onStartRun, onProvenanceClick }: WitnessPanelProps) {
  const { state } = useWitness();
  const [starting, setStarting] = useState(false);
  const [applyingFix, setApplyingFix] = useState(false);
  const [fixDismissed, setFixDismissed] = useState(false);
  const [head, setHead] = useState<string>("");

  async function startCheck(mode: AgentMode) {
    if (!repoId) {
      alert("Connect a folder first.");
      return;
    }
    if (!head) {
      alert("Pick a branch to merge in (the \"with\" dropdown above) first.");
      return;
    }
    setStarting(true);
    setFixDismissed(false);
    try {
      if (mode === "Premortem") {
        const { run_id } = await api.startPremortem(repoId, base, head, [], true, "mock");
        onStartRun(run_id, false);
      }
    } finally {
      setStarting(false);
    }
  }

  async function applyFix() {
    if (!state.runId) return;
    setApplyingFix(true);
    try {
      await api.applyFix(state.runId);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setApplyingFix(false);
    }
  }

  const ledger = state.finalRun?.ledger ?? [];
  const provenLane = state.finalRun?.lanes?.find((l) => l.verdict === "PROVEN");
  const provenGuarantee = ledger.find((g) => g.id === provenLane?.candidate_id?.replace(/^c/, "G"));
  const totalTokens = state.tokenUsage.completion + state.tokenUsage.prompt;

  return (
    <div className="w-[420px] shrink-0 bg-chrome border-l border-border flex flex-col">
      <div className="px-3 py-2.5 border-b border-border flex items-center gap-2">
        <span className="font-semibold text-[13px] tracking-wide text-gray-200">WITNESS</span>
        <div className="ml-auto flex items-center gap-1.5 text-gray-500">
          <button title="checklist">{"☑"}</button>
          <button title="new">{"+"}</button>
          <button title="more">{"⋯"}</button>
        </div>
      </div>

      {!state.runId && (
        <div className="px-3 py-2 border-b border-border flex items-center gap-1.5 text-[12px]">
          <span className="mono text-gray-500">base</span>
          <span className="mono text-gray-300 truncate">{base}</span>
          <span className="text-gray-600">+</span>
          <select
            value={head}
            onChange={(e) => setHead(e.target.value)}
            className="bg-panel border border-border rounded px-1.5 py-0.5 text-gray-300 mono min-w-0"
          >
            <option value="">pick a branch to merge in…</option>
            {branches.filter((b) => b !== base).map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </div>
      )}

      {state.runId && (
        <div className="px-3 py-2 border-b border-border">
          <div className="text-[13px] text-gray-200 truncate">
            Premortem: {base} {"+"} {head}
          </div>
          <div className="mt-1.5 flex items-center gap-2">
            <TokenMeter used={totalTokens} cap={270_000} costUsd={totalTokens * 0.000002} />
            {state.isReplay && (
              <span className="mono text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-gray-400">REPLAY</span>
            )}
            {state.reconnecting && (
              <span className="mono text-[10px] px-1.5 py-0.5 rounded bg-inconclusive/20 text-inconclusive">
                reconnecting…
              </span>
            )}
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {state.runId && <StageList status={state.stageStatus} />}

        {state.runId && (
          <div className="border-b border-border">
            <div className="px-3 py-1.5 text-[11px] uppercase tracking-wide text-gray-500">Blast radius</div>
            {BLAST_AGENTS.map((agent) => (
              <AgentRow
                key={agent}
                name={agent}
                started={state.agentEvents[agent]?.started ?? false}
                done={state.agentEvents[agent]?.done ?? false}
                findings={state.agentEvents[agent]?.findings ?? []}
                onEvidenceClick={onProvenanceClick}
              />
            ))}
          </div>
        )}

        <div className="border-b border-border">
          <div className="px-3 py-1.5 text-[11px] uppercase tracking-wide text-gray-500 flex items-center justify-between">
            <span>Ledger</span>
            <span className="mono text-gray-600">{ledger.length ? `${ledger.length} guarantees` : ""}</span>
          </div>
          <LedgerTable ledger={ledger} onProvenanceClick={onProvenanceClick} />
        </div>

        {state.runId && Object.keys(state.lanes).length > 0 && (
          <div className="border-b border-border">
            <div className="px-3 py-1.5 text-[11px] uppercase tracking-wide text-gray-500">The race</div>
            <div className="grid grid-cols-1 gap-2 px-3 pb-3">
              {Object.values(state.lanes).map((lane) => (
                <LaneCard
                  key={lane.lane_id}
                  lane={lane}
                  candidate={state.finalRun?.candidates?.find((c) => c.id === lane.candidate_id)}
                />
              ))}
            </div>
          </div>
        )}

        {provenLane && (
          <FindingCard lane={provenLane} guarantee={provenGuarantee} onProvenanceClick={onProvenanceClick} />
        )}

        {state.finalRun?.fix && state.finalRun.fix.accepted && !fixDismissed && (
          <FixDiff fix={state.finalRun.fix} onApply={applyFix} onDismiss={() => setFixDismissed(true)} applying={applyingFix} />
        )}

        {state.finalRun && !provenLane && (
          <div className="m-3 rounded border border-border bg-panel/40 px-3 py-4 text-center text-[13px] text-gray-400">
            No guarantee was proven defeated by this change.
          </div>
        )}
      </div>

      <div className="px-3 py-1.5 border-t border-border text-[11px] text-gray-500 flex items-center gap-2">
        <span>{state.finalRun ? "N" : "0"} files changed</span>
        <button className="hover:underline">Undo all</button>
        <button className="hover:underline">Show all</button>
      </div>

      <Composer onSend={(_, mode) => startCheck(mode)} disabled={starting} />
    </div>
  );
}
