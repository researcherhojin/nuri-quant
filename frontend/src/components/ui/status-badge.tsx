/**
 * StatusBadge — BUY/SELL/HOLD 등 상태 표시.
 *
 * intent 5종(pos/neg/warn/info/neutral)으로 수렴 (#1200 U1b-2, Blueprint minimal-tag).
 * 이전의 30-엔트리 클래스 문자열 맵은 같은 스타일이 6번씩 복붙되어 있었고 purple 등
 * 예산 밖 색이 섞여 있었다 — 색 예산(스펙 §1): 인터랙션 blue + intent 4종 + neutral 뿐.
 */
interface StatusBadgeProps {
  status: string;
  size?: "sm" | "md" | "lg";
}

type Intent = "pos" | "neg" | "warn" | "info" | "neutral";

const INTENT_STYLES: Record<Intent, string> = {
  pos: "bg-emerald-500/15 text-emerald-400 border-emerald-500/20",
  neg: "bg-red-500/15 text-red-400 border-red-500/20",
  warn: "bg-amber-500/15 text-amber-400 border-amber-500/20",
  info: "bg-blue-500/15 text-blue-400 border-blue-500/20",
  neutral: "bg-zinc-500/15 text-muted-foreground border-zinc-500/20",
};

const STATUS_INTENT: Record<string, Intent> = {
  // 액션/방향
  BUY: "pos", 매수: "pos", LONG: "pos", 공격: "pos", AGGRESSIVE: "pos", READY: "pos",
  SELL: "neg", 매도: "neg", SHORT: "neg", 방어: "neg", DEFENSIVE: "neg", BLOCKED: "neg",
  REDUCE: "warn", CAUTIOUS: "warn", 주의: "warn",
  HOLD: "neutral", 관망: "neutral", NEUTRAL: "neutral",
  WATCH: "info",
  // 시그널 종류 — breakout 은 이전에 purple(예산 밖)이었음: info 로 수렴
  breakout: "info", momentum: "info",
  bounce: "pos", gap_up: "pos", gap_down: "neg", volume_spike: "warn",
};

export function StatusBadge({ status, size = "sm" }: StatusBadgeProps) {
  const intent = STATUS_INTENT[status] ?? "neutral";
  const style = STATUS_INTENT[status]
    ? INTENT_STYLES[intent]
    : "bg-muted/50 text-muted-foreground border-zinc-600/20";
  const sizeClass = size === "lg" ? "text-sm px-3 py-1" : size === "md" ? "text-xs px-2 py-0.5" : "text-[10px] px-1.5 py-0.5";

  return (
    <span className={`inline-flex items-center rounded-md border font-medium ${style} ${sizeClass}`}>
      {status}
    </span>
  );
}
