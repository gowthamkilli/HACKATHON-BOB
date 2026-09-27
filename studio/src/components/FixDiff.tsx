import type { FixPatch } from "../api/types";

interface FixDiffProps {
  fix: FixPatch;
  onApply: () => void;
  onDismiss: () => void;
  applying?: boolean;
}

export default function FixDiff({ fix, onApply, onDismiss, applying }: FixDiffProps) {
  const lines = fix.unified_diff.split("\n");
  return (
    <div className="m-3 border border-border rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-panel/60 flex items-center justify-between">
        <span className="text-[13px] font-medium text-gray-200">Proposed fix</span>
        <span className="mono text-[11px] text-gray-500">
          +{fix.lines_added} -{fix.lines_removed} · {fix.files_touched.length} file{fix.files_touched.length === 1 ? "" : "s"}
        </span>
      </div>
      <pre className="mono text-[11px] bg-[#0e0e0e] p-2 overflow-x-auto max-h-64">
        {lines.map((line, i) => (
          <div
            key={i}
            className={
              line.startsWith("+") && !line.startsWith("+++")
                ? "text-pass"
                : line.startsWith("-") && !line.startsWith("---")
                  ? "text-fail"
                  : "text-gray-500"
            }
          >
            {line}
          </div>
        ))}
      </pre>
      <div className="px-3 py-2 flex gap-2 border-t border-border">
        <button
          onClick={onApply}
          disabled={applying}
          className="bg-accent text-white text-[12px] rounded px-3 py-1.5 font-medium hover:bg-accent/90 disabled:opacity-50"
        >
          {applying ? "Applying…" : "Apply to branch"}
        </button>
        <button onClick={onDismiss} className="text-[12px] text-gray-400 hover:text-gray-200 px-3 py-1.5">
          Dismiss
        </button>
      </div>
    </div>
  );
}
