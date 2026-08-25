/**
 * VerdictBanner (#1206 U2b-1) — "오늘의 답"이 첫 픽셀.
 *
 * 이전에는 한 줄 판단이 MarketStrip 우측 꼬리(ml-auto·truncate·max-w-40%)에 파묻혀
 * 가장 중요한 문장이 가장 안 보였다 (감사 결함 B-5). 전폭 배너로 승격한다.
 * stale 이면 amber — API verdict 텍스트가 이미 낡은 입력·억제 판단·자동 해제 시점을
 * 서술하므로 (#1181) 배너는 표면화만 담당한다 (Surface rung).
 */
import { verdictLabels } from "./helpers";

const BANNER_STYLES: Record<string, { box: string; tag: string }> = {
  aggressive: { box: "bg-emerald-500/10 border-emerald-500/30", tag: "bg-emerald-500/15 text-emerald-400" },
  neutral:    { box: "bg-zinc-800/40 border-zinc-700/60",       tag: "bg-zinc-500/15 text-zinc-300" },
  cautious:   { box: "bg-amber-500/10 border-amber-500/30",     tag: "bg-amber-500/15 text-amber-400" },
  defensive:  { box: "bg-red-500/10 border-red-500/30",         tag: "bg-red-500/15 text-red-400" },
  stale:      { box: "bg-amber-500/10 border-amber-500/40",     tag: "bg-amber-500/15 text-amber-400" },
};

export function VerdictBanner({ verdict, level }: { verdict: string; level: string }) {
  const s = BANNER_STYLES[level] ?? BANNER_STYLES.neutral;
  const label = verdictLabels[level] ?? verdictLabels.neutral;
  return (
    <div
      data-testid="verdict-banner"
      className={`flex items-center gap-3 px-4 py-2.5 rounded border ${s.box}`}
    >
      <span className={`shrink-0 inline-flex items-center h-5 px-2 rounded font-mono text-[11px] font-semibold ${s.tag}`}>
        {label}
      </span>
      <p className="text-sm font-medium text-zinc-200 min-w-0">{verdict}</p>
    </div>
  );
}
