interface TokenMeterProps {
  used: number;
  cap: number;
  costUsd?: number;
}

function fmt(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

export default function TokenMeter({ used, cap, costUsd }: TokenMeterProps) {
  const pct = Math.min(100, (used / cap) * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="w-24 h-1.5 rounded-full bg-white/10 overflow-hidden">
        <div className="h-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
      <span className="mono text-[11px] text-gray-400">
        {fmt(used)} / {fmt(cap)}
      </span>
      {costUsd !== undefined && (
        <span className="mono text-[11px] px-1.5 py-0.5 rounded-full bg-white/10 text-gray-300">
          ${costUsd.toFixed(3)}
        </span>
      )}
    </div>
  );
}
