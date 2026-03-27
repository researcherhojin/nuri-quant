/**
 * StatusBadge — BUY/SELL/HOLD 등 상태 표시.
 */
interface StatusBadgeProps {
  status: string;
  size?: "sm" | "md";
}

const styles: Record<string, string> = {
  BUY:        "bg-emerald-500/15 text-emerald-400 border-emerald-500/20",
  SELL:       "bg-red-500/15 text-red-400 border-red-500/20",
  HOLD:       "bg-zinc-500/15 text-zinc-400 border-zinc-500/20",
  WATCH:      "bg-blue-500/15 text-blue-400 border-blue-500/20",
  LONG:       "bg-emerald-500/15 text-emerald-400 border-emerald-500/20",
  SHORT:      "bg-red-500/15 text-red-400 border-red-500/20",
  REDUCE:     "bg-amber-500/15 text-amber-400 border-amber-500/20",
  READY:      "bg-emerald-500/15 text-emerald-400 border-emerald-500/20",
  BLOCKED:    "bg-red-500/15 text-red-400 border-red-500/20",
  AGGRESSIVE: "bg-emerald-500/15 text-emerald-400 border-emerald-500/20",
  NEUTRAL:    "bg-zinc-500/15 text-zinc-400 border-zinc-500/20",
  CAUTIOUS:   "bg-amber-500/15 text-amber-400 border-amber-500/20",
  DEFENSIVE:  "bg-red-500/15 text-red-400 border-red-500/20",
  breakout:   "bg-purple-500/15 text-purple-400 border-purple-500/20",
  momentum:   "bg-blue-500/15 text-blue-400 border-blue-500/20",
  bounce:     "bg-emerald-500/15 text-emerald-400 border-emerald-500/20",
  volume_spike: "bg-amber-500/15 text-amber-400 border-amber-500/20",
};

export function StatusBadge({ status, size = "sm" }: StatusBadgeProps) {
  const style = styles[status] || "bg-zinc-700/50 text-zinc-400 border-zinc-600/20";
  const sizeClass = size === "md" ? "text-xs px-2 py-0.5" : "text-[10px] px-1.5 py-0.5";

  return (
    <span className={`inline-flex items-center rounded-md border font-medium ${style} ${sizeClass}`}>
      {status}
    </span>
  );
}
