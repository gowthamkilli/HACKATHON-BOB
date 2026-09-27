import type { Candidate, ExecStatus, LaneResult, Verdict } from "../api/types";

interface LaneCardProps {
  candidate: Candidate | undefined;
  lane: Partial<LaneResult> & { lane_id: string };
}

function resultChip(label: string, status: ExecStatus | undefined | null) {
  if (!status) return <span className="mono text-[11px] text-gray-600">{label} …</span>;
  const color = status === "PASS" ? "text-pass" : status === "FAIL" ? "text-fail" : "text-inconclusive";
  const mark = status === "PASS" ? "✓" : status === "FAIL" ? "✗" : "?";
  return (
    <span className={`mono text-[11px] ${color}`}>
      {label} {mark} {status}
    </span>
  );
}

function verdictBadge(verdict: Verdict | undefined) {
  if (!verdict) return null;
  const styles: Record<Verdict, string> = {
    PROVEN: "bg-pass/20 text-pass",
    DISPROVEN: "bg-fail/20 text-fail",
    INCONCLUSIVE: "bg-inconclusive/20 text-inconclusive",
    INVALID: "bg-invalid/20 text-gray-300",
  };
  return <span className={`mono text-[11px] font-medium px-1.5 py-0.5 rounded ${styles[verdict]}`}>{verdict}</span>;
}

export default function LaneCard({ candidate, lane }: LaneCardProps) {
  const isRunning = !lane.verdict;
  return (
    <div className="border border-border rounded p-2.5 flex flex-col gap-1.5 bg-panel/40">
      <div className="flex items-center justify-between">
        <span className="mono text-[11px] text-gray-500">{lane.lane_id}</span>
        {isRunning ? (
          <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
        ) : (
          verdictBadge(lane.verdict)
        )}
      </div>
      <div className="text-[12px] text-gray-300 line-clamp-2">{candidate?.claim ?? "candidate claim pending…"}</div>
      <div className="flex gap-3">
        {resultChip("base", lane.base_result)}
        {resultChip("head", lane.head_result)}
      </div>
    </div>
  );
}
