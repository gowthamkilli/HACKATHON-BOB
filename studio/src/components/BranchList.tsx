interface BranchListProps {
  branches: string[];
  current: string;
  onSelect: (branch: string) => void;
}

export default function BranchList({ branches, current, onSelect }: BranchListProps) {
  return (
    <div className="px-2 pb-3">
      <div className="text-[11px] uppercase tracking-wide text-gray-500 px-2 py-1.5">Branches</div>
      <div className="flex flex-col">
        {branches.map((branch) => (
          <button
            key={branch}
            onClick={() => onSelect(branch)}
            className={`text-left px-2 py-1 rounded text-[13px] truncate flex items-center gap-1.5 ${
              branch === current ? "bg-accent/15 text-accent" : "text-gray-300 hover:bg-white/5"
            }`}
            title={branch}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${branch === current ? "bg-accent" : "bg-gray-600"}`} />
            <span className="mono truncate">{branch}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
