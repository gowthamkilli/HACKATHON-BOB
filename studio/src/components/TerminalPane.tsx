import { useEffect, useRef } from "react";

interface TerminalPaneProps {
  lines: string[];
}

export default function TerminalPane({ lines }: TerminalPaneProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight });
  }, [lines.length]);

  return (
    <div className="h-40 shrink-0 border-t border-border bg-[#0e0e0e] overflow-hidden flex flex-col">
      <div className="px-3 py-1 text-[11px] uppercase tracking-wide text-gray-500 border-b border-border">Terminal</div>
      <div ref={ref} className="flex-1 overflow-y-auto px-3 py-1.5 mono text-[12px] leading-5">
        {lines.length === 0 && <div className="text-gray-600">Waiting for pipeline events…</div>}
        {lines.map((line, i) => (
          <div
            key={i}
            className={
              line.includes("contributed nothing") || line.startsWith("[error]")
                ? "text-inconclusive"
                : line.includes("PROVEN")
                  ? "text-pass"
                  : line.includes("DISPROVEN") || line.includes("INVALID")
                    ? "text-fail"
                    : "text-gray-400"
            }
          >
            {line}
          </div>
        ))}
      </div>
    </div>
  );
}
