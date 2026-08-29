export const dynamic = "force-dynamic";

import { Fragment, Suspense } from "react";
import Link from "next/link";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/status-badge";
import { Metric } from "@/components/ui/metric";
import { formatMoney } from "@/lib/format";
import { DECISIONS, COMMON } from "@/lib/strings";
import {
  type ActionFilter,
  type OutcomeFilter,
  ACTION_FILTERS,
  OUTCOME_FILTERS,
  OUTCOME_TAG,
  adjudicationInfo,
  filterHref,
  groupByDate,
  parseActionFilter,
  parseOutcomeFilter,
  todayKst,
} from "./helpers";

// === Types ===
interface Decision {
  id: number;
  date: string;
  ticker: string;
  action: string;
  confidence: number;
  regime: string | null;
  // #1303: 결정 시점에 기록된 regime 인지 (백필분은 false)
  regime_has_evidence?: boolean | number;
  macro_score: number | null;
  vix: number | null;
  fear_greed: number | null;
  agreement_rate: number | null;
  entry_price: number | null;
  stop_loss: number | null;
  target_1: number | null;
  target_2: number | null;
  pnl_7d: number | null;
  pnl_30d: number | null;
  pnl_60d: number | null;
  pnl_90d: number | null;
  outcome: string;
  reasoning: string | null;
}

interface DecisionSummary {
  total: number;
  pending: number;
  success: number;
  failure: number;
  neutral: number;
}

interface DecisionResponse {
  decisions: Decision[];
  count: number;
  summary: DecisionSummary;
}

// === Loading ===
function Loading() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="animate-pulse bg-card rounded-xl border border-border h-20" />
        ))}
      </div>
      <div className="animate-pulse bg-card rounded-xl border border-border h-96" />
    </div>
  );
}

// === Metric Cards ===
function SummaryCards({ summary }: { summary: DecisionSummary }) {
  // #1216: 판정 완료 건이 없으면 NaN 이 아니라 — 를 보인다 (0/0 나눗셈 가드)
  const adjudicated = summary.success + summary.failure;
  const successRate = adjudicated > 0 ? Math.round((summary.success / adjudicated) * 100) : null;

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
      <Card className="bg-card border-border">
        <CardContent className="pt-4 pb-3">
          <Metric label="Total" value={summary.total} />
        </CardContent>
      </Card>
      <Card className="bg-card border-border">
        <CardContent className="pt-4 pb-3">
          <Metric label="Pending" value={summary.pending} color="default" />
        </CardContent>
      </Card>
      <Card className="bg-card border-border">
        <CardContent className="pt-4 pb-3">
          <Metric label="Success" value={summary.success} color="green" />
        </CardContent>
      </Card>
      <Card className="bg-card border-border">
        <CardContent className="pt-4 pb-3">
          <Metric label="Failure" value={summary.failure} color="red" />
        </CardContent>
      </Card>
      <Card className="bg-card border-border">
        <CardContent className="pt-4 pb-3">
          <Metric
            label="Hit Rate"
            value={successRate !== null ? `${successRate}%` : "—"}
            color={successRate !== null ? (successRate >= 50 ? "green" : "red") : "default"}
          />
        </CardContent>
      </Card>
    </div>
  );
}

// === Filter bar (#1216) — URL-driven, 서버 컴포넌트 유지 ===
function FilterChip({ href, active, children }: { href: string; active: boolean; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      scroll={false}
      aria-current={active ? "true" : undefined}
      className={`px-2.5 py-1 rounded-sm text-[11px] transition-colors ${
        active ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-900/60"
      }`}
    >
      {children}
    </Link>
  );
}

function FilterBar({ outcome, action }: { outcome: OutcomeFilter | undefined; action: ActionFilter | undefined }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5" data-testid="decisions-filters">
      <div className="flex items-center gap-1">
        <span className="text-[10px] uppercase tracking-wider text-zinc-600 mr-1">{DECISIONS.FILTER_OUTCOME_LABEL}</span>
        <FilterChip href={filterHref(undefined, action)} active={outcome === undefined}>
          {DECISIONS.FILTER_ALL}
        </FilterChip>
        {OUTCOME_FILTERS.map((o) => (
          <FilterChip key={o} href={filterHref(o, action)} active={outcome === o}>
            {OUTCOME_TAG[o].label}
          </FilterChip>
        ))}
      </div>
      <div className="flex items-center gap-1">
        <span className="text-[10px] uppercase tracking-wider text-zinc-600 mr-1">{DECISIONS.FILTER_ACTION_LABEL}</span>
        <FilterChip href={filterHref(outcome, undefined)} active={action === undefined}>
          {DECISIONS.FILTER_ALL}
        </FilterChip>
        {ACTION_FILTERS.map((a) => (
          <FilterChip key={a} href={filterHref(outcome, a)} active={action === a}>
            {a}
          </FilterChip>
        ))}
      </div>
    </div>
  );
}

// === PnL Cell ===
function PnlCell({ value }: { value: number | null }) {
  if (value === null) return <span className="text-muted-foreground">—</span>;
  const color = value > 0 ? "text-emerald-400" : value < 0 ? "text-red-400" : "text-muted-foreground";
  return <span className={`${color} font-mono text-xs tabular-nums`}>{value > 0 ? "+" : ""}{value.toFixed(1)}%</span>;
}

// === 판정 셀 (#1216) — outcome intent 태그 + 판정일/D-n. 성공→BUY 배지 오매핑 제거 ===
function OutcomeCell({ date, outcome, today }: { date: string; outcome: string; today: string }) {
  const tag = OUTCOME_TAG[outcome] ?? OUTCOME_TAG.pending;
  const adj = adjudicationInfo(date, outcome, today);
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-sm ${tag.cls}`}>{tag.label}</span>
      <span className="text-[10px] text-muted-foreground font-mono tabular-nums" title={`${DECISIONS.ADJ_DONE} ${adj.adjudicationDate}`}>
        {adj.kind === "adjudicated" && adj.adjudicationDate}
        {adj.kind === "waiting" && `${DECISIONS.ADJ_DUE_PREFIX}${adj.daysLeft}`}
        {adj.kind === "due" && DECISIONS.ADJ_DUE}
      </span>
    </span>
  );
}

// === Decision Table — 날짜 그룹 헤더 + 밀집 행 (#1216) ===
function DecisionTable({ decisions, filtered, today }: { decisions: Decision[]; filtered: boolean; today: string }) {
  if (decisions.length === 0) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-sm text-muted-foreground">
            {filtered ? (
              DECISIONS.EMPTY_FILTERED
            ) : (
              <>
                {DECISIONS.EMPTY} <code className="text-xs bg-muted px-1 rounded-sm">make consensus</code> {COMMON.RUN_REQUIRED}.
              </>
            )}
          </p>
        </CardContent>
      </Card>
    );
  }

  const groups = groupByDate(decisions);

  return (
    <Card className="bg-card border-border overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted-foreground">
              <th className="px-3 py-2">Ticker</th>
              <th className="px-3 py-2">Action</th>
              <th className="px-3 py-2">Conf</th>
              <th className="px-3 py-2 hidden md:table-cell">Regime</th>
              <th className="px-3 py-2 text-right hidden md:table-cell">Entry</th>
              <th className="px-3 py-2 text-right hidden lg:table-cell">7D</th>
              <th className="px-3 py-2 text-right">30D</th>
              <th className="px-3 py-2 text-right hidden lg:table-cell">90D</th>
              <th className="px-3 py-2">{DECISIONS.ADJ_DONE}</th>
            </tr>
          </thead>
          <tbody>
            {groups.map(([date, rows]) => (
              <Fragment key={date}>
                <tr className="border-b border-border/60 bg-muted/20" data-testid="decisions-date-header">
                  <td colSpan={9} className="px-3 py-1.5 text-[11px] font-mono text-zinc-400">
                    {date} <span className="text-zinc-600">· {rows.length}건</span>
                  </td>
                </tr>
                {rows.map((d) => (
                  <tr
                    key={d.id}
                    className="border-b border-border/40 hover:bg-muted/30 transition-colors"
                    data-testid="decisions-row"
                  >
                    <td className="h-8 px-3 py-1">
                      <Link
                        href={`/decisions/${d.id}`}
                        className="text-primary hover:underline font-medium text-xs"
                      >
                        {d.ticker}
                      </Link>
                    </td>
                    <td className="px-3 py-1"><StatusBadge status={d.action} size="sm" /></td>
                    <td className="px-3 py-1">
                      {/* confidence micro-bar — 대시보드 액션 테이블(#1209)과 동일 패턴 */}
                      <span className="inline-flex items-center gap-1.5">
                        <span className="relative inline-block w-12 h-1 rounded-full bg-zinc-800 overflow-hidden align-middle">
                          <span
                            className="absolute inset-y-0 left-0 rounded-full bg-zinc-500"
                            style={{ width: `${Math.max(0, Math.min(100, d.confidence ?? 0))}%` }}
                          />
                        </span>
                        <span className="text-[11px] text-zinc-400 tabular-nums">{d.confidence?.toFixed(0)}</span>
                      </span>
                    </td>
                    <td className="px-3 py-1 hidden md:table-cell text-xs text-muted-foreground">
                      {d.regime ?? "—"}
                      {d.regime && !d.regime_has_evidence && (
                        <span className="ml-1 text-[9px] text-muted-foreground/60" title={DECISIONS.REGIME_BACKFILLED}>
                          {DECISIONS.REGIME_BACKFILLED_TAG}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-1 text-right hidden md:table-cell font-mono text-xs tabular-nums">
                      {d.entry_price ? formatMoney(d.entry_price, { ticker: d.ticker }) : "—"}
                    </td>
                    <td className="px-3 py-1 text-right hidden lg:table-cell"><PnlCell value={d.pnl_7d} /></td>
                    <td className="px-3 py-1 text-right"><PnlCell value={d.pnl_30d} /></td>
                    <td className="px-3 py-1 text-right hidden lg:table-cell"><PnlCell value={d.pnl_90d} /></td>
                    <td className="px-3 py-1">
                      <OutcomeCell date={d.date} outcome={d.outcome} today={today} />
                    </td>
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// === Main ===
export async function DecisionsSection({
  outcome,
  action,
}: {
  outcome?: OutcomeFilter | undefined;
  action?: ActionFilter | undefined;
} = {}) {
  let data: DecisionResponse;
  try {
    // outcome 은 API 파라미터 (기존 지원), action 은 API 미지원이라 RSC 측 필터
    const qs = outcome ? `&outcome=${outcome}` : "";
    data = await fetchAPI<DecisionResponse>(`/api/decisions?limit=100${qs}`);
  } catch {
    return <p className="text-red-400 text-sm">{COMMON.API_ERROR}</p>;
  }

  const decisions = action ? data.decisions.filter((d) => d.action === action) : data.decisions;
  const today = todayKst();
  const filtered = outcome !== undefined || action !== undefined;

  return (
    <>
      <SummaryCards summary={data.summary} />
      <FilterBar outcome={outcome} action={action} />
      {/* codex R1 P2: 요약 카드는 전역 통계 — 필터 중임을 명시해 혼동을 막는다 */}
      {filtered && (
        <p className="text-[10px] text-zinc-500" data-testid="decisions-filtered-note">
          {decisions.length}{DECISIONS.FILTERED_NOTE_SUFFIX}
        </p>
      )}
      <DecisionTable decisions={decisions} filtered={filtered} today={today} />
    </>
  );
}

export default async function DecisionsPage({
  searchParams,
}: {
  // Defensive: 테스트/페이지 경계 밖 렌더에서는 searchParams 가 없을 수 있다 (page.tsx 동일 패턴)
  searchParams?: Promise<{ outcome?: string; action?: string }> | undefined;
} = {}) {
  const params = (searchParams ? await searchParams : undefined) ?? {};
  const outcome = parseOutcomeFilter(params.outcome);
  const action = parseActionFilter(params.action);
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-bold">Decision Intelligence</h1>
        <p className="text-xs text-muted-foreground">
          {DECISIONS.SUBTITLE}
        </p>
      </div>
      <Suspense fallback={<Loading />}>
        <DecisionsSection outcome={outcome} action={action} />
      </Suspense>
    </div>
  );
}
