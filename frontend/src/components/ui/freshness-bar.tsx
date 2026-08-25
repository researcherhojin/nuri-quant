/**
 * FreshnessBar -- 데이터 소스별 freshness 상태 표시.
 *
 * PASS=emerald, WARN=amber, FAIL=red
 * 각 뱃지: label + age (예: "VIX 2h" or "합의 12h")
 */

interface FreshnessItem {
  key: string;
  label: string;
  status: "PASS" | "WARN" | "FAIL";
  age_hours: number;
  message: string;
}

// FINDING-002 (design-review): 칩이 이미 intent 색(bg+text)을 갖고 있어 컬러 이모지는
// 중복 장식이었다 — 시스템 전역의 이모지 배제 원칙에 맞춰 텍스트 글리프로 (intent 색 상속).
const statusStyles: Record<string, { bg: string; text: string; icon: string }> = {
  PASS: { bg: "bg-emerald-500/15 border-emerald-500/20", text: "text-emerald-400", icon: "\u2713" },
  WARN: { bg: "bg-amber-500/15 border-amber-500/20", text: "text-amber-400", icon: "\u25B3" },
  FAIL: { bg: "bg-red-500/15 border-red-500/20", text: "text-red-400", icon: "\u2715" },
};

function formatAge(hours: number): string {
  if (hours >= 9000) return "N/A";
  if (hours < 1) return "<1h";
  if (hours < 24) return `${Math.round(hours)}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}

export function FreshnessBar({ items }: { items: FreshnessItem[] }) {
  if (!items || items.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item) => {
        const style = statusStyles[item.status] || statusStyles.FAIL;
        return (
          <div
            key={item.key}
            className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] font-medium ${style.bg}`}
            title={item.message}
          >
            <span>{style.icon}</span>
            <span className={style.text}>{item.label}</span>
            <span className="text-muted-foreground/70">{formatAge(item.age_hours)}</span>
          </div>
        );
      })}
    </div>
  );
}

export type { FreshnessItem };
