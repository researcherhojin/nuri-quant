"use client";

/**
 * ConsensusTable — 10-Agent 합의 테이블 + 확장 가능한 에이전트 reasoning.
 *
 * 행 클릭 → 10개 에이전트의 개별 verdict, confidence, reasoning 표시.
 */
import { Fragment, useState } from "react";
import { Ban, TriangleAlert, Vote } from "lucide-react";
import { AgentTrace } from "./agent-trace";
import { StatusBadge } from "./status-badge";

export interface AgentVerdict {
  agent_name: string;
  ticker: string;
  action: string;
  confidence: number;
  reasoning: string;
  data_points: Record<string, unknown>;
}

// A-2c (PR #368): backend scoring_detail contract. Populated by `_build_consensus`
// (consensus.py) when source="consensus"; source="candidate" 도 같은 컬럼을 공유하나
// 이 테이블은 consensus rows 전용.
// Literal union 으로 backend enum 잠금 (codex A-2c review LOW 2 — contract drift 방어).
// export — 회귀 테스트가 같은 literal shape 로 fixture 를 생성할 수 있게.
export type Action = "BUY" | "SELL" | "HOLD";
export type ScoringSource = "consensus" | "candidate";
export type FinalActionSource = "weighted_sum" | "risk_veto" | "divergence_penalty";

export interface ScoringContribution {
  agent_name: string;
  action: Action;
  confidence: number;
  weight: number;
  weighted: number; // weight × (confidence/100) — action_scores[action] 에 누적된 값
  counted_for_basis_action: boolean;
}

export interface ScoringDetail {
  source: ScoringSource;
  schema_version: number;
  weights: Record<string, number>;
  action_scores: Record<Action, number>;
  contributions: ScoringContribution[];
  final_action: Action;
  final_confidence: number;
  final_action_source: FinalActionSource;
  basis_action: Action;
  agreement_rate: number;
  risk_veto_fired: boolean;
  divergence_flag: boolean;
  penalty_applied: boolean;
  pre_penalty_action: Action | "";
}

export interface ConsensusRow {
  ticker: string;
  final_action: string;
  final_confidence: number;
  agreement_rate: number;
  verdicts: AgentVerdict[];
  dissent: string[];
  reasoning: string;
  divergence_flag?: boolean;
  divergence_reason?: string;
  scoring_detail?: ScoringDetail | null;
}

const AGENT_ORDER = [
  { key: "technical", label: "Tech" },
  { key: "fundamental", label: "Fund" },
  { key: "macro", label: "Macro" },
  { key: "risk", label: "Risk" },
  { key: "smart_money", label: "Smart" },
  { key: "wallstreet", label: "Wall" },
  { key: "korean_market", label: "KR" },
  { key: "options", label: "Opt" },
  { key: "crypto", label: "Cry" },
  { key: "retail", label: "Ret" },
];

function agentCell(verdict: AgentVerdict | undefined) {
  if (!verdict) return <span className="text-muted-foreground/40">--</span>;
  const icon = verdict.action === "BUY" ? "B" : verdict.action === "SELL" ? "S" : "H";
  const color = verdict.action === "BUY"
    ? "text-emerald-400"
    : verdict.action === "SELL"
    ? "text-red-400"
    : "text-muted-foreground";
  return (
    <span className={`${color} font-mono text-[11px]`}>
      {icon}{Math.round(verdict.confidence)}
    </span>
  );
}

// A-2c: `final_action_source` 를 한국어 tooltip + 아이콘으로 시각화.
// satisfies 로 backend literal union 과 key exhaustiveness 연결 (codex review LOW 2).
// 아이콘은 이모지가 아닌 lucide (#1238 아이콘 체계, design-review F-003) — ReactNode 로
// 보관해 컴포넌트-타입 프롭 충돌(TS6 gotcha)을 피한다.
const SOURCE_META = {
  weighted_sum: { icon: <Vote className="inline size-3 text-zinc-400" aria-hidden />, tip: "가중 합의" },
  risk_veto: { icon: <Ban className="inline size-3 text-red-400" aria-hidden />, tip: "리스크 에이전트 거부권 (Risk SELL conf ≥ 80)" },
  divergence_penalty: { icon: <TriangleAlert className="inline size-3 text-amber-400" aria-hidden />, tip: "기술지표 반대로 HOLD 강등" },
} satisfies Record<FinalActionSource, { icon: React.ReactNode; tip: string }>;

export function ConsensusTable({ data, vix }: { data: ConsensusRow[]; vix?: number | null }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border">
            <th className="py-1.5 px-2 text-left font-medium text-muted-foreground">Ticker</th>
            <th className="py-1.5 px-2 text-center font-medium text-muted-foreground">Action</th>
            <th className="py-1.5 px-2 text-right font-medium text-muted-foreground">Conf</th>
            <th className="py-1.5 px-2 text-right font-medium text-muted-foreground hidden sm:table-cell">Agree</th>
            {AGENT_ORDER.map((a) => (
              <th key={a.key} className="py-1.5 px-1.5 text-center font-medium text-muted-foreground hidden md:table-cell">
                {a.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row) => {
            const isExpanded = expanded === row.ticker;
            const agentMap = Object.fromEntries(
              row.verdicts.map((v) => [v.agent_name, v])
            );

            return (
              <Fragment key={row.ticker}>
                <tr
                  className={`border-b border-border/40 hover:bg-muted/30 transition-colors cursor-pointer ${
                    isExpanded ? "bg-muted/20" : ""
                  }`}
                  onClick={() => setExpanded(isExpanded ? null : row.ticker)}
                >
                  <td className="py-1.5 px-2 font-medium">{row.ticker}</td>
                  <td className="py-1.5 px-2 text-center">
                    <StatusBadge status={row.final_action} size="md" />
                    {vix && vix >= 25 && vix < 30 && row.final_action === "BUY" && (
                      <span className="text-amber-400 text-[10px] ml-1">(반포지션)</span>
                    )}
                    {row.divergence_flag && (
                      <span
                        className="text-amber-400 text-[10px] ml-1 cursor-help"
                        title={row.divergence_reason || "기술지표 반대"}
                        data-testid="divergence-badge"
                      >
                        <TriangleAlert className="inline size-3" aria-hidden />
                      </span>
                    )}
                    {/* A-2c: final_action_source 가 weighted_sum 이 아니면 아이콘으로 override 원인 surface.
                        basis_action ≠ final_action 인 penalty 케이스에는 "pre_penalty → final" 미니 텍스트. */}
                    {row.scoring_detail && row.scoring_detail.final_action_source !== "weighted_sum" && (
                      <span
                        className="text-[10px] ml-1 cursor-help"
                        title={SOURCE_META[row.scoring_detail.final_action_source]?.tip || row.scoring_detail.final_action_source}
                        data-testid="action-source-badge"
                      >
                        {SOURCE_META[row.scoring_detail.final_action_source]?.icon || "·"}
                      </span>
                    )}
                    {row.scoring_detail?.penalty_applied && row.scoring_detail.basis_action !== row.final_action && (
                      <div
                        className="text-[9px] text-amber-400/80 mt-0.5 leading-tight"
                        data-testid="penalty-basis-label"
                      >
                        {row.scoring_detail.pre_penalty_action} → {row.final_action}
                      </div>
                    )}
                  </td>
                  <td className="py-1.5 px-2 text-right">{row.final_confidence.toFixed(1)}</td>
                  <td className="py-1.5 px-2 text-right hidden sm:table-cell">
                    <span className={row.agreement_rate >= 0.7 ? "text-emerald-400" : row.agreement_rate < 0.5 ? "text-red-400" : "text-muted-foreground"}>
                      {(row.agreement_rate * 100).toFixed(0)}%
                    </span>
                  </td>
                  {AGENT_ORDER.map((a) => (
                    <td key={a.key} className="py-1.5 px-1.5 text-center hidden md:table-cell">
                      {agentCell(agentMap[a.key])}
                    </td>
                  ))}
                </tr>
                {isExpanded && (
                  <tr className="bg-muted/10">
                    <td colSpan={4 + AGENT_ORDER.length} className="px-3 py-3">
                      {/* A-2c: contributions 에서 agent 별 weighted 값을 lookup.
                          분모는 basis_action bucket 의 action_scores 합 — "basis 방향 결정에 얼마나
                          기여했는가" 가 UI 의도 (codex review LOW 1 — 전체 총합 분모는 semantic drift).
                          basis_action 과 반대쪽 agent 의 `%` 는 null 로 렌더 (basis 기여 아니므로 무의미). */}
                      {(() => {
                        const sd = row.scoring_detail;
                        const contribMap = Object.fromEntries(
                          (sd?.contributions ?? []).map((c) => [c.agent_name, c])
                        );
                        const basisDenom = sd?.action_scores[sd.basis_action] ?? 0;
                        return (
                          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                            {AGENT_ORDER.map((a) => {
                              const v = agentMap[a.key];
                              if (!v) return null;
                              const contrib = contribMap[a.key];
                              // basis 방향에 기여한 에이전트만 % 계산 (의미 있는 causal share).
                              const pctOfBasis = contrib?.counted_for_basis_action && basisDenom > 0
                                ? (contrib.weighted / basisDenom) * 100
                                : null;
                              return (
                                <div
                                  key={a.key}
                                  className={`bg-muted/30 rounded-md p-2 border ${
                                    contrib?.counted_for_basis_action
                                      ? "border-emerald-500/40"
                                      : "border-border/30"
                                  }`}
                                  data-testid={`agent-card-${a.key}`}
                                >
                                  <div className="flex items-center gap-2 mb-1">
                                    <span className="text-[10px] font-medium text-muted-foreground">{a.label}</span>
                                    <StatusBadge status={v.action} size="sm" />
                                    <span className="text-[10px] text-muted-foreground ml-auto">{v.confidence.toFixed(0)}%</span>
                                  </div>
                                  {contrib && (
                                    <div className="flex items-center gap-1 mb-1 text-[9px] text-muted-foreground/80">
                                      <span title={`weighted = ${contrib.weight} × ${contrib.confidence}/100 = ${contrib.weighted}`}>
                                        w={contrib.weight.toFixed(3)} · c={contrib.weighted.toFixed(3)}
                                      </span>
                                      {pctOfBasis !== null && (
                                        <span
                                          className="ml-auto font-mono"
                                          data-testid={`contrib-pct-${a.key}`}
                                          title={`${sd?.basis_action} 방향 결정 기여도 (action_scores[${sd?.basis_action}] 대비)`}
                                        >
                                          {pctOfBasis.toFixed(0)}%
                                        </span>
                                      )}
                                    </div>
                                  )}
                                  <p className="text-[10px] text-muted-foreground/80 leading-tight">{v.reasoning}</p>
                                </div>
                              );
                            })}
                          </div>
                        );
                      })()}
                      {/* 에이전트 reasoning trace — 실시간 스트리밍 */}
                      <div className="mt-3 pt-3 border-t border-border/20">
                        <AgentTrace ticker={row.ticker} />
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
