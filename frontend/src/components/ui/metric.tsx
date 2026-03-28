/**
 * Metric — 숫자 지표 표시 컴포넌트.
 */
interface MetricProps {
  label: string;
  value: string | number;
  sub?: string;
  color?: "green" | "red" | "default";
  size?: "sm" | "lg";
}

export function Metric({ label, value, sub, color = "default", size = "sm" }: MetricProps) {
  const colorClass =
    color === "green" ? "text-emerald-400" :
    color === "red" ? "text-red-400" : "text-zinc-200";

  const sizeClass = size === "lg" ? "text-xl" : "text-sm";

  return (
    <div>
      <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</p>
      <p className={`${sizeClass} font-semibold ${colorClass}`}>{value}</p>
      {sub && <p className="text-[10px] text-muted-foreground/70">{sub}</p>}
    </div>
  );
}
