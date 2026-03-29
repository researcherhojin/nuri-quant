"use client";

import { useState, useEffect, useCallback, memo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Card, CardContent } from "@/components/ui/card";

// === Types ===
interface DashboardData {
  regime?: { regime?: string; label?: string };
  macro?: { score?: number };
  gate?: { ready?: boolean };
  gate_score?: number;
  n_positions?: number;
}

interface CertifyData {
  certified?: boolean;
  score?: number;
  conditions?: Array<{ name: string; passed: boolean; detail: string }>;
}

interface PipelineNodeData {
  label: string;
  sub: string;
  status: "ok" | "warning" | "error";
  href?: string;
  detail?: string;
  lastRun?: string;
  [key: string]: unknown;
}

interface TimelineEntry {
  step: string;
  status: "ok" | "warning" | "error";
  detail: string;
  time: string;
}

// === 상태 색상 매핑 ===
const STATUS_COLORS: Record<string, string> = {
  ok: "bg-emerald-500",
  warning: "bg-amber-500",
  error: "bg-red-500",
};

const STATUS_BORDER: Record<string, string> = {
  ok: "border-emerald-500/30",
  warning: "border-amber-500/30",
  error: "border-red-500/30",
};

const STATUS_GLOW: Record<string, string> = {
  ok: "shadow-emerald-500/10",
  warning: "shadow-amber-500/10",
  error: "shadow-red-500/10",
};

const STATUS_TEXT: Record<string, string> = {
  ok: "text-emerald-400",
  warning: "text-amber-400",
  error: "text-red-400",
};

// === Custom Node Component (확장된 정보 표시) ===
const PipelineNode = memo(({ data }: { data: PipelineNodeData }) => {
  const status = data.status || "ok";

  return (
    <div
      className={`
        relative bg-card border rounded-xl px-6 py-5 min-w-[240px]
        cursor-pointer transition-all duration-200
        hover:bg-muted/80 hover:scale-[1.02]
        shadow-lg ${STATUS_GLOW[status]}
        ${STATUS_BORDER[status]}
      `}
      onClick={() => {
        if (data.href) window.location.href = data.href;
      }}
    >
      {/* 입력 핸들 */}
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-muted !border-border !w-2 !h-2"
      />

      {/* 상태 표시 + 스텝 번호 */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-lg">{data.label.split(" ")[0]}</span>
        <span className="relative flex h-2.5 w-2.5">
          <span
            className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${STATUS_COLORS[status]}`}
          />
          <span
            className={`relative inline-flex rounded-full h-2.5 w-2.5 ${STATUS_COLORS[status]}`}
          />
        </span>
      </div>

      {/* 제목 */}
      <p className="text-base font-bold text-foreground mb-0.5">
        {data.label.split(" ").slice(1).join(" ")}
      </p>

      {/* 부제 */}
      <p className="text-xs text-muted-foreground">{data.sub}</p>

      {/* 상세 정보 (추가) */}
      {data.detail && (
        <p className={`text-[10px] mt-1.5 font-medium ${STATUS_TEXT[status]}`}>
          {data.detail}
        </p>
      )}

      {/* 마지막 실행 시간 */}
      {data.lastRun && (
        <p className="text-[10px] text-muted-foreground/60 mt-1">
          {data.lastRun}
        </p>
      )}

      {/* 출력 핸들 */}
      <Handle
        type="source"
        position={Position.Right}
        className="!bg-muted !border-border !w-2 !h-2"
      />
    </div>
  );
});

PipelineNode.displayName = "PipelineNode";

// === Edges (6-step pipeline: Collect → Validate → Classify → Diagnose → Recommend → Track) ===
const EDGES: Edge[] = [
  { id: "e-collect-validate", source: "collect", target: "validate", animated: true, style: { stroke: "#3f3f46" } },
  { id: "e-validate-classify", source: "validate", target: "classify", animated: true, style: { stroke: "#3f3f46" } },
  { id: "e-classify-diagnose", source: "classify", target: "diagnose", animated: true, style: { stroke: "#3f3f46" } },
  { id: "e-diagnose-recommend", source: "diagnose", target: "recommend", animated: true, style: { stroke: "#3f3f46" } },
  { id: "e-recommend-track", source: "recommend", target: "track", animated: true, style: { stroke: "#3f3f46" } },
];

// === 상대 시간 포맷 ===
function formatRelativeTime(dateStr: string): string {
  const now = new Date();
  const date = new Date(dateStr);
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);

  if (diffMin < 1) return "방금";
  if (diffMin < 60) return `${diffMin}분 전`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}시간 전`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}일 전`;
}

// === Page Component ===
export default function PipelinePage() {
  const [regime, setRegime] = useState<string>("loading");
  const [macroScore, setMacroScore] = useState<number | null>(null);
  const [certified, setCertified] = useState<boolean | null>(null);
  const [siegeScore, setSiegeScore] = useState<number | null>(null);
  const [gateReady, setGateReady] = useState<boolean | null>(null);
  const [gateScore, setGateScore] = useState<number | null>(null);
  const [nPositions, setNPositions] = useState<number | null>(null);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);

  // API에서 실시간 상태 조회
  useEffect(() => {
    const entries: TimelineEntry[] = [];
    const now = new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });

    // 대시보드 데이터 (regime, macro, gate)
    fetch("http://localhost:8001/api/dashboard")
      .then((r) => (r.ok ? r.json() : null))
      .then((data: DashboardData | null) => {
        if (data) {
          setRegime(data.regime?.regime || data.regime?.label || "unknown");
          setGateReady(data.gate_score ? data.gate_score >= 50 : null);
          setGateScore(data.gate_score ?? null);
          setMacroScore(data.macro?.score ?? null);
          setNPositions(data.n_positions ?? null);

          entries.push({
            step: "Collect",
            status: data.gate_score && data.gate_score >= 50 ? "ok" : "warning",
            detail: `게이트 스코어 ${data.gate_score ?? "N/A"}%`,
            time: now,
          });
          entries.push({
            step: "Classify",
            status: data.regime?.regime ? "ok" : "warning",
            detail: `레짐: ${data.regime?.regime || "unknown"}`,
            time: now,
          });
        }
      })
      .catch(() => setRegime("error"));

    // SIEGE 인증 상태
    fetch("http://localhost:8001/api/certify")
      .then((r) => (r.ok ? r.json() : null))
      .then((data: CertifyData | null) => {
        if (data) {
          setCertified(data.certified ?? false);
          setSiegeScore(data.score ?? null);

          const passed = data.conditions?.filter(c => c.passed).length ?? 0;
          const total = data.conditions?.length ?? 0;
          entries.push({
            step: "Diagnose",
            status: data.certified ? "ok" : "error",
            detail: `SIEGE ${passed}/${total} 조건 통과`,
            time: now,
          });
        }
      })
      .catch(() => setCertified(false));

    // Scorecard 데이터
    fetch("http://localhost:8001/api/scorecard")
      .then((r) => (r.ok ? r.json() : null))
      .then((data: Array<{ signal_id: string; total_trades: number; win_rate: number }> | null) => {
        if (data && Array.isArray(data)) {
          const totalTrades = data.reduce((sum, s) => sum + (s.total_trades || 0), 0);
          entries.push({
            step: "Validate",
            status: "ok",
            detail: `${data.length}개 시그널, ${totalTrades.toLocaleString()} trades 검증`,
            time: now,
          });
        }
      })
      .catch(() => {});

    // Consensus 데이터
    fetch("http://localhost:8001/api/consensus")
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { results?: Array<{ final_action: string }> } | null) => {
        if (data?.results) {
          const buys = data.results.filter((r: { final_action: string }) => r.final_action === "BUY").length;
          const sells = data.results.filter((r: { final_action: string }) => r.final_action === "SELL").length;
          entries.push({
            step: "Recommend",
            status: "ok",
            detail: `BUY ${buys}건, SELL ${sells}건 추천`,
            time: now,
          });
        }
      })
      .catch(() => {});

    // 타임라인 업데이트 (지연)
    const timer = setTimeout(() => setTimeline([...entries]), 2000);
    return () => clearTimeout(timer);
  }, []);

  // 레짐 상태 → 노드 status 변환
  const regimeStatus = (): "ok" | "warning" | "error" => {
    if (regime === "loading" || regime === "error") return "warning";
    if (regime === "crisis" || regime === "volatile_bear") return "error";
    return "ok";
  };

  // 게이트 상태 → 노드 status 변환
  const gateStatus = (): "ok" | "warning" | "error" => {
    if (gateReady === null) return "warning";
    return gateReady ? "ok" : "error";
  };

  // 파이프라인 노드 정의 (6-step: Collect → Validate → Classify → Diagnose → Recommend → Track)
  const nodes: Node[] = [
    {
      id: "collect",
      type: "pipeline",
      position: { x: 0, y: 80 },
      data: {
        label: "📡 Collect",
        sub: "21 collectors + 10 외부 사이트",
        status: gateStatus(),
        href: "/portfolio",
        detail: gateScore !== null ? `게이트: ${gateScore}%` : undefined,
      },
    },
    {
      id: "validate",
      type: "pipeline",
      position: { x: 320, y: 80 },
      data: {
        label: "✅ Validate",
        sub: "시그널 백테스트 + 스코어카드",
        status: "ok",
        href: "/signals",
        detail: "승률/PF 검증",
      },
    },
    {
      id: "classify",
      type: "pipeline",
      position: { x: 640, y: 80 },
      data: {
        label: "📊 Classify",
        sub: `6 regimes — ${regime}`,
        status: regimeStatus(),
        href: "/strategy",
        detail: macroScore !== null ? `매크로: ${macroScore}/100` : undefined,
      },
    },
    {
      id: "diagnose",
      type: "pipeline",
      position: { x: 960, y: 80 },
      data: {
        label: "🤖 Diagnose",
        sub: "7 agents 합의 분석",
        status: certified === null ? "warning" : certified ? "ok" : "error",
        href: "/consensus",
        detail: siegeScore !== null ? `SIEGE: ${siegeScore}%` : undefined,
      },
    },
    {
      id: "recommend",
      type: "pipeline",
      position: { x: 1280, y: 80 },
      data: {
        label: "📋 Recommend",
        sub: "매매 후보 + 가격 타겟",
        status: "ok",
        href: "/targets",
        detail: "BUY/SELL 후보 선별",
      },
    },
    {
      id: "track",
      type: "pipeline",
      position: { x: 1600, y: 80 },
      data: {
        label: "📈 Track",
        sub: "30/60/90일 성과 추적",
        status: "ok",
        href: "/engine",
        detail: nPositions !== null ? `${nPositions}개 포지션` : undefined,
      },
    },
  ];

  // nodeTypes를 useCallback으로 메모이제이션 (리렌더 방지)
  const nodeTypes = useCallback(
    () => ({ pipeline: PipelineNode }),
    [],
  );

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Pipeline</h1>
        <div className="flex items-center gap-4">
          {/* 레짐 배지 */}
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">Regime</span>
            <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${
              regimeStatus() === "ok"
                ? "bg-emerald-400/10 text-emerald-400"
                : regimeStatus() === "error"
                ? "bg-red-400/10 text-red-400"
                : "bg-amber-400/10 text-amber-400"
            }`}>
              {regime.toUpperCase()}
            </span>
          </div>
          {/* SIEGE 배지 */}
          {certified !== null && (
            <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-medium ${
              certified ? "bg-emerald-400/10 text-emerald-400" : "bg-red-400/10 text-red-400"
            }`}>
              <span>{certified ? "CERTIFIED" : "REJECTED"}</span>
              {siegeScore !== null && (
                <span className="opacity-60">{siegeScore}%</span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* React Flow 캔버스 */}
      <div className="h-[320px] rounded-xl border border-border bg-background overflow-hidden">
        <ReactFlow
          nodes={nodes}
          edges={EDGES}
          nodeTypes={nodeTypes()}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          proOptions={{ hideAttribution: true }}
          minZoom={0.5}
          maxZoom={1.5}
          defaultEdgeOptions={{
            type: "smoothstep",
            animated: true,
          }}
        >
          <Background color="#27272a" gap={20} size={1} />
          <Controls
            showInteractive={false}
            className="!bg-card !border-input !shadow-lg [&>button]:!bg-muted [&>button]:!border-input [&>button]:!text-muted-foreground [&>button:hover]:!bg-muted"
          />
        </ReactFlow>
      </div>

      {/* 하단 범례 */}
      <div className="flex items-center gap-6 text-[10px] text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <span className="inline-flex h-2 w-2 rounded-full bg-emerald-500" />
          <span>정상</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-flex h-2 w-2 rounded-full bg-amber-500" />
          <span>로딩 / 경고</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-flex h-2 w-2 rounded-full bg-red-500" />
          <span>오류 / 실패</span>
        </div>
        <span className="text-muted-foreground/50">|</span>
        <span>노드를 클릭하면 상세 페이지로 이동합니다</span>
      </div>

      {/* 파이프라인 실행 타임라인 */}
      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-xs text-zinc-500 mb-3">최근 파이프라인 실행 현황</p>
          {timeline.length === 0 ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="inline-block w-3 h-3 border-2 border-muted-foreground/30 border-t-muted-foreground rounded-full animate-spin" />
              <span>파이프라인 상태 조회 중...</span>
            </div>
          ) : (
            <div className="space-y-2">
              {timeline.map((entry, i) => (
                <div key={i} className="flex items-center gap-3 text-xs">
                  {/* 상태 인디케이터 */}
                  <span className={`inline-flex h-2 w-2 rounded-full shrink-0 ${STATUS_COLORS[entry.status]}`} />
                  {/* 스텝 이름 */}
                  <span className="text-muted-foreground w-24 shrink-0 font-medium">{entry.step}</span>
                  {/* 상세 정보 */}
                  <span className="text-foreground">{entry.detail}</span>
                  {/* 시간 */}
                  <span className="ml-auto text-muted-foreground/60 text-[10px]">{entry.time}</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 파이프라인 단계별 요약 카드 */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Card className="bg-card border-border">
          <CardContent className="pt-4 pb-3">
            <p className="text-[10px] text-muted-foreground mb-1">Collect</p>
            <p className="text-sm font-bold">21 collectors</p>
            <p className="text-[10px] text-muted-foreground/70">10 외부 데이터 소스</p>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardContent className="pt-4 pb-3">
            <p className="text-[10px] text-muted-foreground mb-1">Classify</p>
            <p className={`text-sm font-bold ${STATUS_TEXT[regimeStatus()]}`}>{regime.toUpperCase()}</p>
            <p className="text-[10px] text-muted-foreground/70">
              {macroScore !== null ? `매크로 ${macroScore}/100` : "매크로 로딩 중"}
            </p>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardContent className="pt-4 pb-3">
            <p className="text-[10px] text-muted-foreground mb-1">SIEGE</p>
            <p className={`text-sm font-bold ${certified ? "text-emerald-400" : certified === null ? "text-muted-foreground" : "text-red-400"}`}>
              {certified === null ? "로딩 중" : certified ? "CERTIFIED" : "REJECTED"}
            </p>
            <p className="text-[10px] text-muted-foreground/70">
              {siegeScore !== null ? `${siegeScore}% 스코어` : "10-condition 검증"}
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
