interface RailProps {
  active: "explorer" | "search" | "scm" | "run" | "witness" | "settings";
  onSelect: (tab: RailProps["active"]) => void;
}

const ICONS: { key: RailProps["active"]; label: string; glyph: string }[] = [
  { key: "explorer", label: "Explorer", glyph: "☰" },
  { key: "search", label: "Search", glyph: "\u{1F50D}" },
  { key: "scm", label: "Source Control", glyph: "⎇" },
  { key: "run", label: "Run", glyph: "▶" },
  { key: "witness", label: "Witness", glyph: "✓" },
  { key: "settings", label: "Settings", glyph: "⚙" },
];

export default function Rail({ active, onSelect }: RailProps) {
  return (
    <div className="w-12 shrink-0 bg-chrome border-r border-border flex flex-col items-center py-3 gap-1">
      {ICONS.map((icon) => (
        <button
          key={icon.key}
          title={icon.label}
          onClick={() => onSelect(icon.key)}
          className={`w-9 h-9 rounded flex items-center justify-center text-lg transition-colors ${
            active === icon.key
              ? "bg-panel text-accent border-l-2 border-accent"
              : "text-gray-500 hover:text-gray-200 hover:bg-panel/60"
          }`}
        >
          {icon.glyph}
        </button>
      ))}
    </div>
  );
}
