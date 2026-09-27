import type { Guarantee } from "../api/types";

interface LedgerTableProps {
  ledger: Guarantee[];
  onProvenanceClick: (site: string) => void;
}

export default function LedgerTable({ ledger, onProvenanceClick }: LedgerTableProps) {
  if (ledger.length === 0) {
    return <div className="px-3 py-3 text-[13px] text-gray-500">No guarantees loaded yet.</div>;
  }
  return (
    <div className="px-1 py-2">
      {ledger.map((g) => (
        <div key={g.id} className="flex items-start gap-2 px-2 py-1.5 hover:bg-white/5 rounded text-[12px]">
          <span className="mono text-gray-400 w-7 shrink-0">{g.id}</span>
          <div className="min-w-0 flex-1">
            <div className="text-gray-300 truncate" title={g.statement}>
              {g.statement}
            </div>
            <div className="flex flex-wrap gap-1 mt-0.5">
              {g.provenance.map((site) => (
                <button key={site} onClick={() => onProvenanceClick(site)} className="mono text-[10px] text-gray-500 hover:text-accent hover:underline">
                  {site}
                </button>
              ))}
            </div>
          </div>
          <span
            className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium mono ${
              g.covered_by_test ? "bg-pass/15 text-pass" : "bg-inconclusive/15 text-inconclusive"
            }`}
          >
            {g.covered_by_test ? "covered" : "UNCOVERED"}
          </span>
        </div>
      ))}
    </div>
  );
}
