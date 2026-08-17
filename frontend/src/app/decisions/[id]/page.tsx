export const dynamic = "force-dynamic";

import { Suspense } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { fetchAPI } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/status-badge";
import { Metric } from "@/components/ui/metric";

// === Types ===
interface Evidence {
  id: number;
  decision_id: number;
  source_type: string;
  source_key: string;
  action: string | null;
  confidence: number | null;
  detail: string | null;
}

interface AgentVerdict {
  agent_name: string;
  action: string;
  confidence: number;
  reasoning?: string;
  [key: string]: unknown;
}

interface ThesisEvidence {
  id: number;
  side: "bull" | "bear";
  claim: string;
  source_type: string;
  source_key: string | null;
  source_url: string | null;
  as_of: string | null;
  quote: string | null;
}

interface Thesis {
  id: number;
  ticker: string;
  version: number;
  author: string;
  stance: string;
  bull_case: string;
  bear_case: string;
  effective_date: string;
  status: string;
  verdict: string | null;
  evidence: ThesisEvidence[];
}

interface DecisionDetail {
  id: number;
  date: string;
  ticker: string;
  action: string;
  confidence: number;
  regime: string | null;
  macro_score: number | null;
  vix: number | null;
  fear_greed: number | null;
  agreement_rate: number | null;
  agent_verdicts: AgentVerdict[] | string | null;
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
  evidence: Evidence[];
  // 결정 시점(`date`)에 유효했던 논지 — point-in-time 조인이라 논지를 나중에 써도
  // 그 이전 결정들에 소급해 붙는다. 논지가 없으면 null.
  thesis: Thesis | null;
}

// agent_verdicts 는 JSON 문자열로 저장됨 — 안전 파싱 + per-item 검증.
function parseVerdicts(raw: AgentVerdict[] | string | null): AgentVerdict[] {
  let arr: unknown = raw;
  if (typeof raw === "string") {
    try {
      arr = JSON.parse(raw);
    } catch {
      return [];
    }
  }
  if (!Array.isArray(arr)) return [];
  // 불량 항목(null/[{}]/타입 불일치) 제거 — agent_name·action 문자열만 통과.
  return arr.filter(
    (v): v is AgentVerdict =>
      v != null &&
      typeof v === "object" &&
      typeof (v as AgentVerdict).agent_name === "string" &&
      typeof (v as AgentVerdict).action === "string",
  );
}

function pnlColor(v: number | null): "green" | "red" | "default" {
  if (v === null) return "default";
  return v > 0 ? "green" : v < 0 ? "red" : "default";
}

function fmt(v: number | null, suffix = ""): string {
  return v === null ? "—" : `${v}${suffix}`;
}

// === Provenance (exported for test coverage of async children — frontend RSC gotcha) ===
export async function DecisionProvenance({ id }: { id: string }) {
  let d: DecisionDetail | null = null;
  try {
    d = await fetchAPI<DecisionDetail>(`/api/decisions/${id}`);
  } catch {
    notFound();
  }
  if (!d) notFound();

  const verdicts = parseVerdicts(d.agent_verdicts);
  const evidence = d.evidence ?? [];

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <Link href="/decisions" className="text-xs text-muted-foreground hover:text-foreground">
            ← Decisions
          </Link>
          <h1 className="text-xl font-semibold text-foreground">{d.ticker}</h1>
          <StatusBadge status={d.action} />
          <span className="text-xs text-muted-foreground">#{d.id} · {d.date}</span>
        </div>
        {d.outcome && <StatusBadge status={d.outcome} />}
      </div>

      {/* Decision-time context (frozen) */}
      <Card className="bg-card border-border">
        <CardContent className="pt-4 pb-3">
          <p className="text-[10px] text-muted-foreground mb-3">결정 시점 컨텍스트 (frozen)</p>
          <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
            <Metric label="Confidence" value={fmt(d.confidence, "%")} />
            <Metric label="Agreement" value={d.agreement_rate === null ? "—" : `${Math.round(d.agreement_rate * 100)}%`} />
            <Metric label="Regime" value={d.regime ?? "—"} />
            <Metric label="VIX" value={fmt(d.vix)} />
            <Metric label="Fear&Greed" value={fmt(d.fear_greed)} />
            <Metric label="Macro" value={fmt(d.macro_score)} />
          </div>
        </CardContent>
      </Card>

      {/* Price ladder */}
      <Card className="bg-card border-border">
        <CardContent className="pt-4 pb-3">
          <p className="text-[10px] text-muted-foreground mb-3">가격 레벨</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Metric label="Entry" value={fmt(d.entry_price)} />
            <Metric label="Stop" value={fmt(d.stop_loss)} color="red" />
            <Metric label="Target 1" value={fmt(d.target_1)} color="green" />
            <Metric label="Target 2" value={fmt(d.target_2)} color="green" />
          </div>
        </CardContent>
      </Card>

      {/* Outcome (forward PnL) */}
      <Card className="bg-card border-border">
        <CardContent className="pt-4 pb-3">
          <p className="text-[10px] text-muted-foreground mb-3">실현 결과 (forward PnL %)</p>
          <div className="grid grid-cols-4 gap-3">
            <Metric label="7d" value={fmt(d.pnl_7d, "%")} color={pnlColor(d.pnl_7d)} />
            <Metric label="30d" value={fmt(d.pnl_30d, "%")} color={pnlColor(d.pnl_30d)} />
            <Metric label="60d" value={fmt(d.pnl_60d, "%")} color={pnlColor(d.pnl_60d)} />
            <Metric label="90d" value={fmt(d.pnl_90d, "%")} color={pnlColor(d.pnl_90d)} />
          </div>
        </CardContent>
      </Card>

      {/* Thesis — 상승/하락 논리 병기 (#1083). 없으면 카드 자체를 숨기지 않고
          "아직 없음" 을 보여준다: 논지가 비어 있다는 사실이 곧 판단 근거의 부재라
          화면에서 사라지면 안 된다. */}
      <Card className="bg-card border-border">
        <CardContent className="pt-4 pb-3">
          <div className="flex items-baseline gap-2 mb-3">
            <p className="text-[10px] text-muted-foreground">투자 논지</p>
            {d.thesis && (
              <span className="text-[10px] text-muted-foreground/70">
                v{d.thesis.version} · {d.thesis.effective_date} · {d.thesis.author} · {d.thesis.status}
                {d.thesis.verdict ? ` · ${d.thesis.verdict}` : ""}
              </span>
            )}
          </div>
          {!d.thesis ? (
            <p className="text-xs text-muted-foreground">
              이 시점에 기록된 논지 없음 — 무엇이 맞으면 이 판단이 옳고 무엇이 틀리면 그른지가 남아 있지 않다.
            </p>
          ) : (
            <div className="space-y-3">
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded bg-muted/40 px-2.5 py-2">
                  <p className="text-[10px] text-emerald-500 mb-1">상승 논리</p>
                  <p className="text-xs text-foreground/90 whitespace-pre-wrap">{d.thesis.bull_case}</p>
                </div>
                <div className="rounded bg-muted/40 px-2.5 py-2">
                  <p className="text-[10px] text-rose-500 mb-1">하락 논리</p>
                  <p className="text-xs text-foreground/90 whitespace-pre-wrap">{d.thesis.bear_case}</p>
                </div>
              </div>
              {d.thesis.evidence.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-[10px] text-muted-foreground">논지 근거 ({d.thesis.evidence.length})</p>
                  {d.thesis.evidence.map((e) => (
                    <div key={e.id} className="flex items-start gap-2 text-xs bg-muted/40 rounded px-2.5 py-1.5">
                      <span
                        className={`w-10 shrink-0 ${e.side === "bull" ? "text-emerald-500" : "text-rose-500"}`}
                      >
                        {e.side === "bull" ? "상승" : "하락"}
                      </span>
                      <span className="text-foreground/90">{e.claim}</span>
                      <span className="ml-auto shrink-0 text-[10px] text-muted-foreground font-mono">
                        {e.source_url ? (
                          <a href={e.source_url} className="underline" rel="noopener noreferrer" target="_blank">
                            {e.source_type}
                            {e.source_key ? `/${e.source_key}` : ""}
                          </a>
                        ) : (
                          <>
                            {e.source_type}
                            {e.source_key ? `/${e.source_key}` : ""}
                          </>
                        )}
                        {e.as_of ? ` · ${e.as_of}` : ""}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Reasoning */}
      {d.reasoning && (
        <Card className="bg-card border-border">
          <CardContent className="pt-4 pb-3">
            <p className="text-[10px] text-muted-foreground mb-2">근거</p>
            <p className="text-sm text-foreground/90 whitespace-pre-wrap">{d.reasoning}</p>
          </CardContent>
        </Card>
      )}

      {/* Agent verdicts */}
      {verdicts.length > 0 && (
        <Card className="bg-card border-border">
          <CardContent className="pt-4 pb-3">
            <p className="text-[10px] text-muted-foreground mb-3">에이전트 판정 ({verdicts.length})</p>
            <div className="space-y-1.5">
              {verdicts.map((v, i) => (
                <div key={i} className="flex items-center gap-2 text-xs bg-muted/40 rounded px-2.5 py-1.5">
                  <span className="w-28 shrink-0 text-muted-foreground">{v.agent_name}</span>
                  <StatusBadge status={v.action} />
                  <span className="text-foreground/60">
                    {typeof v.confidence === "number" ? `${Math.round(v.confidence)}%` : "—"}
                  </span>
                  {typeof v.reasoning === "string" && (
                    <span className="truncate text-foreground/70">{v.reasoning}</span>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Evidence chain (provenance) */}
      <Card className="bg-card border-border">
        <CardContent className="pt-4 pb-3">
          <p className="text-[10px] text-muted-foreground mb-3">증거 체인 ({evidence.length})</p>
          {evidence.length === 0 ? (
            <p className="text-xs text-muted-foreground">증거 없음</p>
          ) : (
            <div className="space-y-1.5">
              {evidence.map((e) => (
                <div key={e.id} className="flex items-start gap-2 text-xs bg-muted/40 rounded px-2.5 py-1.5">
                  <span className="w-32 shrink-0 text-muted-foreground">{e.source_type}/{e.source_key}</span>
                  {e.action && <StatusBadge status={e.action} />}
                  {e.confidence !== null && <span className="text-foreground/60 shrink-0">{Math.round(e.confidence)}%</span>}
                  {e.detail && <span className="truncate text-foreground/70 font-mono text-[10px]">{e.detail}</span>}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Loading() {
  return (
    <div className="space-y-5">
      <div className="h-8 bg-card rounded w-64 animate-pulse" />
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="h-28 bg-card rounded-xl border border-border animate-pulse" />
      ))}
    </div>
  );
}

export default async function DecisionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense fallback={<Loading />}>
      <DecisionProvenance id={id} />
    </Suspense>
  );
}
