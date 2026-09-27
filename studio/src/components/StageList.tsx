import { STAGES } from "../api/types";
import type { StageStatus } from "../state/store";

interface StageListProps {
  status: Record<string, StageStatus>;
}

const LABELS: Record<string, string> = {
  intake: "intake",
  blast: "blast radius (5)",
  delta: "delta",
  race: "race (5)",
  confirm: "confirm",
  fix: "fix",
  report: "report",
};

function icon(status: StageStatus): string {
  if (status === "done") return "✓";
  if (status === "running") return "⣾";
  return "·";
}

export default function StageList({ status }: StageListProps) {
  const allDone = STAGES.every((s) => status[s] === "done");
  const doneCount = STAGES.filter((s) => status[s] === "done").length;

  return (
    <div className="px-3 py-2 border-b border-border">
      {STAGES.map((stage) => (
        <div
          key={stage}
          className={`flex items-center gap-2 py-0.5 text-[13px] ${
            status[stage] === "done" ? "text-pass" : status[stage] === "running" ? "text-accent" : "text-gray-500"
          }`}
        >
          <span className="w-4 text-center">{icon(status[stage])}</span>
          <span className="mono">{LABELS[stage]}</span>
        </div>
      ))}
      {allDone && (
        <div className="mt-2 rounded bg-pass/15 text-pass text-[13px] font-medium px-2 py-1.5">
          All stages complete {"✓"} {doneCount}/{STAGES.length}
        </div>
      )}
    </div>
  );
}
