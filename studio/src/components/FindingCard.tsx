import { useState } from "react";
import type { Guarantee, LaneResult } from "../api/types";

interface FindingCardProps {
  lane: LaneResult;
  guarantee: Guarantee | undefined;
  testSource?: string;
  onProvenanceClick: (site: string) => void;
}

export default function FindingCard({ lane, guarantee, testSource, onProvenanceClick }: FindingCardProps) {
  const [copied, setCopied] = useState(false);
  const reproCommand = `python -m engine.cli replay --run <run-id>  # or re-run the proof test directly:\npytest ${lane.test_path}`;

  function copyTest() {
    if (!testSource) return;
    navigator.clipboard.writeText(testSource);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="m-3 border border-fail/40 rounded-lg overflow-hidden">
      <div className="bg-fail/10 px-3 py-2 flex items-center gap-2">
        <span className="text-fail font-semibold text-[13px]">DEFEATED</span>
        <span className="mono text-[12px] text-gray-300">{guarantee?.id ?? lane.candidate_id}</span>
      </div>
      <div className="p-3 flex flex-col gap-2 text-[12px]">
        <div className="text-gray-200">{guarantee?.statement ?? "guarantee statement unavailable"}</div>
        {guarantee?.why && <div className="text-gray-500">why: {guarantee.why}</div>}
        <div className="flex flex-wrap gap-1">
          {(guarantee?.provenance ?? []).map((site) => (
            <button key={site} onClick={() => onProvenanceClick(site)} className="mono text-[11px] text-accent hover:underline">
              {site}
            </button>
          ))}
        </div>
        {testSource && (
          <div className="relative">
            <pre className="mono text-[11px] bg-[#0e0e0e] border border-border rounded p-2 overflow-x-auto max-h-48">
              {testSource}
            </pre>
            <button
              onClick={copyTest}
              className="absolute top-1.5 right-1.5 text-[10px] bg-white/10 hover:bg-white/20 rounded px-1.5 py-0.5 text-gray-300"
            >
              {copied ? "copied" : "copy"}
            </button>
          </div>
        )}
        <div className="mono text-[11px] text-gray-500 bg-panel/60 rounded p-2 whitespace-pre-wrap">{reproCommand}</div>
      </div>
    </div>
  );
}
