interface StatusBarProps {
  branch: string;
  findingsCount: number;
  errorCount?: number;
  warningCount?: number;
}

export default function StatusBar({ branch, findingsCount, errorCount = 0, warningCount = 0 }: StatusBarProps) {
  return (
    <div className="h-6 shrink-0 bg-accent text-white text-[12px] flex items-center px-3 gap-4 select-none">
      <span className="flex items-center gap-1">
        <span>{"⎇"}</span>
        <span className="mono">{branch}</span>
      </span>
      <span>
        {errorCount} {"✖"} {warningCount} {"⚠"}
      </span>
      <span className="ml-auto">Witness: {findingsCount} findings</span>
    </div>
  );
}
