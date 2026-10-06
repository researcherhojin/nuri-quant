"use client";

import Link from "next/link";
import { Fragment, useId, useState } from "react";
import { OPPORTUNITY, SYSTEM_STANCE } from "@/lib/strings";
import { stanceLabel, stanceText, stanceTone, type SystemStance } from "@/lib/system-stance";

interface AgentVerdict {
  ticker: string;
  action: string;
  confidence: number;
  agreement: number;
  divergence_flag?: boolean;
  divergence_reason?: string;
}

export interface Opportunity {
  ticker: string;
  price: number | null;
  change_1d: number | null;
  change_5d: number | null;
  volume_ratio: number | null;
  rsi: number | null;
  signal: string | null;
  score: number | null;
  // #1683: 스캐너가 본 사실 — 판정이 아니다
  observations: string[];
  // 파이프라인(BUY 후보 emitter)의 분류 — 판정은 API 가 아니라 여기서 온다
  system: SystemStance;
}

interface OpportunityExplorerProps {
  opportunities: Opportunity[];
}

const toneStyles = {
  positive: { bg: "bg-emerald-500/20", text: "text-emerald-400" },
  neutral: { bg: "bg-amber-500/20", text: "text-amber-400" },
  danger: { bg: "bg-red-500/20", text: "text-red-400" },
  muted: { bg: "bg-zinc-700/50", text: "text-zinc-400" },
} satisfies Record<string, { bg: string; text: string }>;

function actionTagCls(action: string): string {
  if (action === "BUY") return "bg-emerald-500/20 text-emerald-400";

  if (action === "SELL") return "bg-red-500/20 text-red-400";

  return "bg-zinc-700 text-zinc-400";
}

// 머리글 11px — UX plan §1 의 라벨 규격. 액션 테이블(action-items.tsx)도 같은 값 (Codex #1652 P2, 둘 다 9px 에서 올림).
const TH = "px-2 py-1 text-[11px] font-medium text-zinc-600";

/**
 * #1652 U6: 카드 → 액션 테이블과 같은 32px 행 + quick-peek.
 * #1683: 판정 칸은 파이프라인 분류(`system`)이고, 스캐너 관측은 첫 줄만 보이다가 펼치면 전부 나온다.
 */
function OpportunityRow({ opp }: { opp: Opportunity }) {
  const [expanded, setExpanded] = useState(false);
  const [analysis, setAnalysis] = useState<AgentVerdict | null>(null);
  const [loading, setLoading] = useState(false);
  const peekId = useId();

  const runAnalysis = async () => {
    setLoading(true);

    try {
      const res = await fetch(`/api/consensus/${opp.ticker}`);

      if (res.ok) {
        const data = await res.json();
        setAnalysis({
          ticker: opp.ticker,
          action: data.final_action ?? data.action ?? "HOLD",
          confidence: data.final_confidence ?? data.confidence ?? 0,
          agreement: data.agreement_rate ? Math.round(data.agreement_rate * 100) : 0,
          divergence_flag: data.divergence_flag ?? false,
          divergence_reason: data.divergence_reason ?? "",
        });
      }
    } catch {
      // silent — button stays available for retry
    } finally {
      setLoading(false);
    }
  };

  const style = toneStyles[stanceTone(opp.system)];
  const label = stanceLabel(opp.system);
  const text = stanceText(opp.system);
  const change5d = opp.change_5d ?? 0;
  const change5dColor = change5d >= 0 ? "text-emerald-400" : "text-red-400";
  const rsiColor = opp.rsi == null ? "" : opp.rsi < 30 ? "text-emerald-400" : opp.rsi > 70 ? "text-red-400" : "text-zinc-500";

  return (
    <Fragment>
      <tr
        className="border-b border-zinc-800/40 hover:bg-zinc-800/30 cursor-pointer transition-colors"
        onClick={() => setExpanded(!expanded)}
        data-testid="opportunity-row"
      >
        <td className="h-8 px-2 whitespace-nowrap">
          <button
            type="button"
            aria-expanded={expanded}
            aria-controls={peekId}
            aria-label={`${opp.ticker} ${expanded ? OPPORTUNITY.PEEK_COLLAPSE : OPPORTUNITY.PEEK_EXPAND}`}
            onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
            className="mr-1 align-middle inline-flex items-center justify-center size-4 -my-1 rounded-sm text-zinc-500 hover:text-zinc-200 transition-colors focus-visible:outline-2 focus-visible:outline-blue-400/75"
          >
            <span aria-hidden="true" className={`text-[9px] leading-none transition-transform ${expanded ? "rotate-90" : ""}`}>&#9654;</span>
          </button>
          <Link
            href={`/ticker/${opp.ticker}`}
            className="text-xs font-semibold text-zinc-100 hover:text-white transition-colors"
            onClick={(e) => e.stopPropagation()}
          >
            {opp.ticker}
          </Link>
        </td>
        <td className="h-8 px-2 whitespace-nowrap text-xs text-zinc-300 tabular-nums">${opp.price?.toFixed(2) ?? "—"}</td>
        <td className="h-8 px-2 whitespace-nowrap">
          {opp.signal && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-sm bg-blue-500/15 text-blue-400">{opp.signal}</span>
          )}
        </td>
        <td className="h-8 px-2 whitespace-nowrap">
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-sm ${style.bg} ${style.text}`} title={text} data-testid="system-stance">
            {label}
          </span>
        </td>
        <td className="h-8 px-2 max-w-0 w-[40%]">
          <p className="text-[11px] text-zinc-400 truncate" title={opp.observations.join(" · ")}>
            {opp.observations[0] ?? <span className="text-zinc-700">—</span>}
            {opp.observations.length > 1 && <span className="text-zinc-600"> +{opp.observations.length - 1}</span>}
          </p>
        </td>
        <td className="h-8 px-2 whitespace-nowrap text-[11px] tabular-nums">
          <span className={change5dColor}>5D {change5d >= 0 ? "+" : ""}{opp.change_5d?.toFixed(1) ?? 0}%</span>
          {opp.volume_ratio != null && opp.volume_ratio >= 1.5 && (
            <span className="ml-2 text-amber-400">Vol {opp.volume_ratio.toFixed(1)}x</span>
          )}
          {opp.rsi != null && <span className={`ml-2 ${rsiColor}`}>RSI {Math.round(opp.rsi)}</span>}
        </td>
        <td className="h-8 px-2 whitespace-nowrap text-right text-[10px]">
          {analysis ? (
            <span className="inline-flex items-center gap-1.5" data-testid="opportunity-analysis">
              <span className={`font-bold px-1.5 py-0.5 rounded-sm ${actionTagCls(analysis.action)}`}>{analysis.action}</span>
              <span className="text-zinc-400">{OPPORTUNITY.VERDICT} {analysis.confidence}</span>
              <span className="text-zinc-500">{analysis.agreement}{OPPORTUNITY.AGREEMENT_SUFFIX}</span>
              {analysis.divergence_flag && (
                <span
                  className="text-amber-400 font-medium cursor-help"
                  title={analysis.divergence_reason || "기술지표 반대"}
                  data-testid="divergence-badge"
                >
                  ⚠ Tech
                </span>
              )}
            </span>
          ) : (
            <button
              onClick={(e) => { e.stopPropagation(); void runAnalysis(); }}
              disabled={loading}
              className="text-blue-400 hover:text-blue-300 transition-colors disabled:opacity-50"
            >
              {loading ? OPPORTUNITY.ANALYZING : OPPORTUNITY.ANALYZE + " ▶"}
            </button>
          )}
          <Link
            href={`/ticker/${opp.ticker}`}
            className="ml-3 inline-block p-1.5 -m-1.5 text-zinc-500 hover:text-zinc-300 transition-colors"
            onClick={(e) => e.stopPropagation()}
          >
            {OPPORTUNITY.CHART} →
          </Link>
        </td>
      </tr>
      {expanded && (
        <tr id={peekId} className="border-b border-zinc-800/40 bg-zinc-900/40" data-testid="opportunity-row-peek">
          <td colSpan={7} className="px-3 py-2">
            <p className="text-[11px] text-zinc-300">
              <span className="text-zinc-500 mr-1.5">{OPPORTUNITY.SYSTEM}</span>
              <span className={`font-bold ${style.text}`}>{text}</span>
            </p>
            <p className="text-[10px] text-zinc-600 mb-1.5">{SYSTEM_STANCE.NOTE}</p>
            <div className="text-[11px]">
              <span className="text-zinc-500 font-semibold">{OPPORTUNITY.OBSERVATIONS}</span>
              {opp.observations.length === 0 && <span className="ml-2 text-zinc-600">—</span>}
              {opp.observations.map((o, i) => <p key={i} className="text-zinc-400 leading-tight mt-0.5">{o}</p>)}
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  );
}

export function OpportunityExplorer({ opportunities }: OpportunityExplorerProps) {
  if (opportunities.length === 0) {
    return (
      <div className="rounded-lg bg-zinc-900/40 border border-zinc-800/60 p-4 text-center text-sm text-zinc-500">
        {OPPORTUNITY.EMPTY}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-sm border border-zinc-800/60 bg-zinc-900/30">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-zinc-800/40">
            <th scope="col" className={TH}>{OPPORTUNITY.COL_TICKER}</th>
            <th scope="col" className={TH}>{OPPORTUNITY.COL_PRICE}</th>
            <th scope="col" className={TH}>{OPPORTUNITY.COL_SIGNAL}</th>
            <th scope="col" className={TH}>{OPPORTUNITY.SYSTEM}</th>
            <th scope="col" className={TH}>{OPPORTUNITY.OBSERVATIONS}</th>
            <th scope="col" className={TH}>{OPPORTUNITY.COL_METRICS}</th>
            <th scope="col" className="px-2 py-1" />
          </tr>
        </thead>
        <tbody>
          {opportunities.map((opp) => <OpportunityRow key={opp.ticker} opp={opp} />)}
        </tbody>
      </table>
    </div>
  );
}
