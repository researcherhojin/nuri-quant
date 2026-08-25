/**
 * MarketStrip (#1204 U2a) — market + allocation compact strip (1 row).
 * page.tsx #223 iter 7c IIFE 에서 추출, 동작 불변. 데이터 있는 지표만 렌더 —
 * "VIX — —" / "권장 0% / 100%" 류 placeholder 를 만들지 않는다.
 */
import { MARKET } from "@/lib/strings";
import { trendKo, vixZone, fgLabel, fgColor, macroLevel } from "./helpers";

export interface Allocation { long: number; short: number; cash: number }

interface MarketStripProps {
  trend: string;
  vix: number | null;
  fg: number | null;
  macroScore: number | undefined;
  actualAllocation?: Allocation;
  targetAllocation?: Allocation | null;
  fallbackAllocation?: Allocation | null;
  verdict: string;
  verdictTextClass: string;
}

export function MarketStrip({
  trend, vix, fg, macroScore,
  actualAllocation, targetAllocation, fallbackAllocation,
  verdict, verdictTextClass,
}: MarketStripProps) {
  // actual: API always provides this in real responses; mock tests
  // sometimes don't, so default to a sentinel that still renders.
  const actual = actualAllocation ?? { long: 0, short: 0, cash: 100 };
  const target = targetAllocation ?? fallbackAllocation ?? null;
  // Hide 권장 entirely when it's the meaningless 0/100 default
  // (means "no regime data") or matches actual.
  const hasMeaningfulTarget =
    target != null &&
    (target.long > 0 || target.short > 0) &&
    !(target.long === actual.long && target.cash === actual.cash);
  const hasMacroScore = typeof macroScore === "number" && macroScore > 0;
  const vixInfo = vixZone(vix);
  const macroInfo = macroLevel(macroScore ?? 0);

  return (
    <div className="flex items-center gap-3 flex-wrap text-[10px] text-zinc-500 px-2 py-1.5 rounded bg-zinc-900/40 border border-zinc-800/60">
      <span className={trend === "bull" ? "text-emerald-400 font-semibold" : trend === "bear" ? "text-red-400 font-semibold" : "text-amber-400 font-semibold"}>
        {trendKo(trend)}
      </span>
      {vix != null && (
        <span>
          VIX <span className={`font-semibold tabular-nums ${vixInfo.color}`}>{Math.round(vix * 10) / 10}</span> <span className={vixInfo.color}>{vixInfo.label}</span>
        </span>
      )}
      {fg != null && (
        <span>
          {MARKET.SENTIMENT} <span className={`inline-flex items-center justify-center h-4 w-4 rounded-full text-[9px] font-bold tabular-nums ${fgColor(fg)}`}>{fg}</span> <span className="text-zinc-600">{fgLabel(fg)}</span>
        </span>
      )}
      {hasMacroScore && (
        <span>
          {MARKET.ECONOMY} <span className={`font-semibold tabular-nums ${macroInfo.color}`}>{macroScore}</span> <span className={macroInfo.color}>{macroInfo.label}</span>
        </span>
      )}
      <span className="text-zinc-700">·</span>
      <span>
        {MARKET.ACTUAL} <span className="text-emerald-400 font-semibold tabular-nums">{actual.long}%</span> {MARKET.INVEST} / <span className="text-zinc-300 font-semibold tabular-nums">{actual.cash}%</span> {MARKET.CASH}
      </span>
      {hasMeaningfulTarget && target && (
        <>
          <span className="text-zinc-700">→</span>
          <span className="text-zinc-600">
            {MARKET.TARGET} <span className="text-emerald-500 tabular-nums">{target.long}%</span> / <span className="text-zinc-500 tabular-nums">{target.cash}%</span>
          </span>
        </>
      )}
      <span className={`ml-auto text-[10px] ${verdictTextClass} truncate max-w-[40%]`} title={verdict}>
        {verdict}
      </span>
    </div>
  );
}
