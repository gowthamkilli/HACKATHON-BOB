import { useState } from "react";
import type { BlastFinding } from "../api/types";

interface AgentRowProps {
  name: string;
  started: boolean;
  done: boolean;
  findings: BlastFinding[];
  onEvidenceClick: (site: string) => void;
}

export default function AgentRow({ name, started, done, findings, onEvidenceClick }: AgentRowProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border-b border-border/60">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-[13px] hover:bg-white/5"
        disabled={!started}
      >
        <span
          className={`w-3.5 h-3.5 rounded-full flex items-center justify-center text-[9px] shrink-0 ${
            !started ? "bg-white/10 text-gray-600" : done ? "bg-pass/20 text-pass" : "bg-accent/20 text-accent animate-pulse"
          }`}
        >
          {done ? "✓" : started ? "•" : ""}
        </span>
        <span className="mono text-gray-300">{name}</span>
        <span className="text-gray-500 ml-auto text-[12px]">
          {done ? `${findings.length} finding${findings.length === 1 ? "" : "s"}` : started ? "thinking…" : "queued"}
        </span>
        {done && findings.length > 0 && <span className="text-gray-500">{open ? "▾" : "▸"}</span>}
      </button>
      {open && findings.length > 0 && (
        <div className="pb-2 px-3 flex flex-col gap-1.5">
          {findings.map((f, i) => (
            <div key={i} className="text-[12px] bg-panel/60 rounded p-2 border border-border">
              <div className="text-gray-300">{f.claim}</div>
              <div className="mt-1 flex flex-wrap gap-1">
                {f.evidence.map((site) => (
                  <button
                    key={site}
                    onClick={() => onEvidenceClick(site)}
                    className="mono text-[11px] text-accent hover:underline"
                  >
                    {site}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
