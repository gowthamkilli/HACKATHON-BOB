interface DiffPaneProps {
  baseLabel: string;
  headLabel: string;
  baseContent: string;
  headContent: string;
  touchedLines?: number[];
}

// Minimal LCS-based line diff -- no external dependency, matches "no component library."
function diffLines(a: string[], b: string[]): { type: "same" | "add" | "del"; text: string }[] {
  const dp: number[][] = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const result: { type: "same" | "add" | "del"; text: string }[] = [];
  let i = 0, j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      result.push({ type: "same", text: a[i] });
      i++; j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      result.push({ type: "del", text: a[i] });
      i++;
    } else {
      result.push({ type: "add", text: b[j] });
      j++;
    }
  }
  while (i < a.length) result.push({ type: "del", text: a[i++] });
  while (j < b.length) result.push({ type: "add", text: b[j++] });
  return result;
}

export default function DiffPane({ baseLabel, headLabel, baseContent, headContent }: DiffPaneProps) {
  const rows = diffLines(baseContent.split("\n"), headContent.split("\n"));

  return (
    <div className="flex-1 min-h-0 overflow-auto mono text-[13px] bg-panel">
      <div className="grid grid-cols-2 sticky top-0 bg-panel border-b border-border z-10">
        <div className="px-3 py-1.5 text-gray-400 border-r border-border truncate">{baseLabel}</div>
        <div className="px-3 py-1.5 text-gray-400 truncate">{headLabel}</div>
      </div>
      <div>
        {rows.map((row, idx) => (
          <div
            key={idx}
            className={`grid grid-cols-2 ${
              row.type === "add" ? "bg-pass/10" : row.type === "del" ? "bg-fail/10" : ""
            }`}
          >
            <div className={`px-3 border-r border-border whitespace-pre ${row.type === "del" ? "text-fail" : row.type === "add" ? "opacity-30" : "text-gray-300"}`}>
              {row.type !== "add" ? (row.type === "del" ? "- " : "  ") + row.text : ""}
            </div>
            <div className={`px-3 whitespace-pre ${row.type === "add" ? "text-pass" : row.type === "del" ? "opacity-30" : "text-gray-300"}`}>
              {row.type !== "del" ? (row.type === "add" ? "+ " : "  ") + row.text : ""}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
