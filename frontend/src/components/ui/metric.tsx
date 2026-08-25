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
    color === "red" ? "text-red-400" : "text-foreground";

  const sizeClass = size === "lg" ? "text-xl" : "text-sm";

  return (
    <div>
      {/* 라벨 11px (#1200 U1b-2, WCAG 실측 — 10px faint 는 소형 텍스트 기준 미달이었음) */}
      <p className="text-[11px] text-muted-foreground uppercase tracking-wider">{label}</p>
      {/* 숫자 지표는 mono — 자릿수 무관 정렬 (스펙 §1 타이포) */}
      <p className={`${sizeClass} font-mono font-semibold ${colorClass}`}>{value}</p>
      {sub && <p className="text-[10px] text-muted-foreground/70">{sub}</p>}
    </div>
  );
}
