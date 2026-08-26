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
import {
  BarChart3,
  Bot,
  Check,
  CheckCircle2,
  Circle,
  ClipboardList,
  Cog,
  MapPin,
  Play,
  Search,
  Users,
  X,
} from "lucide-react";
import { ERRORS, PIPELINE as PL } from "@/lib/strings";
import { summarizePayload } from "./helpers";

// design-review F-005: 6노드 선형 DAG 가 피치 300(행폭 ~1,680px)로 캔버스에 fit 되며
// 0.46배로 축소돼 기본 줌에서 노드 텍스트가 판독 불가였다 — 피치 축소로 fit 배율 회복.
// 노드 자체가 min-w-55(220px)라 피치는 220 + 간격이어야 엣지가 보인다 (220이면 간격 0).
const NODE_PITCH_X = 264;

// === Types ===
interface PipelineStep {
  step: string;
  label: string;
  description: string;
  record_count: number;
  last_updated: string | null;
  status: "idle" | "running" | "done" | "error";
  started_at: string | null;
  error: string | null;
}

interface PipelineStatusData {
  steps: PipelineStep[];
}

interface TimelineEvent {
  timestamp: string;
  event_type: "start" | "success" | "error";
  step: string;
  payload: Record<string, unknown>;
}

interface GateCondition {
  id: string;
  phase: string;
  description: string;
  passed: boolean;
  detail: string;
}

interface GateResult {
  phase: string;
  total: number;
  passed: number;
  score: number;
  ready: boolean;
  conditions: GateCondition[];
}

interface PipelineNodeData {
  label: string;
  sub: string;
  status: "ok" | "warning" | "error" | "running";
  recordCount: number;
  lastUpdated: string | null;
  stepId: string;
  onRun: (stepId: string) => void;
  isRunning: boolean;
  href?: string;
  [key: string]: unknown;
}

// === 상태 색상 매핑 ===
const STATUS_COLORS: Record<string, string> = {
  ok: "bg-emerald-500",
  warning: "bg-amber-500",
  error: "bg-red-500",
  running: "bg-blue-500",
};

const STATUS_BORDER: Record<string, string> = {
  ok: "border-emerald-500/30",
  warning: "border-amber-500/30",
  error: "border-red-500/30",
  running: "border-blue-500/30",
};

const STATUS_GLOW: Record<string, string> = {
  ok: "shadow-emerald-500/10",
  warning: "shadow-amber-500/10",
  error: "shadow-red-500/10",
  running: "shadow-blue-500/10",
};

// F-003 (#1237): 이모지 → lucide — 디자인 시스템의 유일한 아이콘 체계 (사이드바와 동일).
// lucide 의 LucideIcon 별칭은 TS6 JSX 에서 붕괴 사례가 있어 구체 타입(typeof Search)으로.
type IconComponent = typeof Search;

// 키 2계보: DEFAULT_NODES 어휘(validate/classify/diagnose/recommend) + 라이브 API 어휘
// (analyze/consensus/certify — README 스테이지 표). 구 이모지 맵은 후자가 없어 라이브
// 노드가 무아이콘이었다. 아이콘은 사이드바 아이덴티티와 일치 (Signals=BarChart3,
// Agents=Users, Certification Engine=Cog).
const STEP_ICONS: Record<string, IconComponent> = {
  collect: Search,
  validate: CheckCircle2,
  classify: BarChart3,
  diagnose: Bot,
  recommend: ClipboardList,
  analyze: BarChart3,
  consensus: Users,
  certify: Cog,
  track: MapPin,
};

const STEP_HREFS: Record<string, string> = {
  collect: "/engine",
  validate: "/signals",
  classify: "/strategy",
  diagnose: "/consensus",
  recommend: "/targets",
  track: "/targets",
};

// 타임라인 이벤트 아이콘
const EVENT_ICONS: Record<string, IconComponent> = {
  start: Play,
  success: Check,
  error: X,
};

function formatAge(dateStr: string | null): string {
  if (!dateStr) return "N/A";
  try {
    const dt = new Date(dateStr);
    const now = new Date();
    const hours = (now.getTime() - dt.getTime()) / (1000 * 60 * 60);
    if (hours < 1) return "<1h ago";
    if (hours < 24) return `${Math.round(hours)}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  } catch {
    return dateStr;
  }
}

// F-003: 이벤트 아이콘 — 뱃지와 같은 intent 색 (success=emerald, error=red, start=blue)
export function EventIcon({ type }: { type: string }) {
  const Icon = EVENT_ICONS[type] ?? Circle;
  const color =
    type === "success" ? "text-emerald-400" : type === "error" ? "text-red-400" : "text-blue-400";
  return <Icon size={13} className={`shrink-0 mt-0.5 ${color}`} aria-hidden="true" data-testid={`event-icon-${type}`} />;
}

function formatTimestamp(iso: string): string {
  try {
    const dt = new Date(iso);
    return dt.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso;
  }
}

// F-003: 미지의 step 은 중립 원 — 라이브 데이터가 새 step 을 내보내도 깨지지 않게
export function StepIcon({ stepId }: { stepId: string }) {
  const Icon = STEP_ICONS[stepId] ?? Circle;
  // aria-hidden 명시: lucide 기본값에 기대지 않는다 — 장식 아이콘 (codex #1238 P3, 잠금은 branchcov 테스트)
  return <Icon size={15} className="text-muted-foreground" aria-hidden="true" data-testid={`step-icon-${stepId}`} />;
}

// === Custom Node Component ===
export const PipelineNode = memo(({ data }: { data: PipelineNodeData }) => {
  const status = data.status || "ok";

  return (
    <div
      className={`
        relative bg-card border rounded-xl px-5 py-4 min-w-55
        transition-all duration-200
        hover:bg-muted/80 hover:scale-[1.02]
        shadow-lg ${STATUS_GLOW[status]}
        ${STATUS_BORDER[status]}
      `}
    >
      {/* 입력 핸들 */}
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-muted !border-border !w-2 !h-2"
      />

      {/* 상태 표시 + 라벨 — F-003: stepId 기반 lucide 아이콘 (label 은 제목만) */}
      <div className="flex items-center justify-between mb-1.5">
        <StepIcon stepId={data.stepId} />
        <div className="flex items-center gap-2">
          {/* 레코드 수 */}
          <span className="text-[10px] text-muted-foreground/70">{data.recordCount.toLocaleString()}</span>
          {/* 상태 점 */}
          <span className="relative flex h-2.5 w-2.5">
            {status === "running" ? (
              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${STATUS_COLORS[status]}`} />
            ) : null}
            <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${STATUS_COLORS[status]}`} />
          </span>
        </div>
      </div>

      {/* 제목 */}
      <p className="text-sm font-bold text-foreground mb-0.5">
        {data.label}
      </p>

      {/* 부제 + last updated */}
      <p className="text-[10px] text-muted-foreground">{data.sub}</p>
      <p className="text-[10px] text-muted-foreground/50 mt-0.5">{formatAge(data.lastUpdated)}</p>

      {/* 실행 버튼 */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          if (!data.isRunning) data.onRun(data.stepId);
        }}
        disabled={data.isRunning}
        className={`
          mt-2 w-full text-[10px] font-medium py-1 rounded-md border transition-all
          ${data.isRunning
            ? "bg-blue-500/10 border-blue-500/20 text-blue-400 cursor-wait"
            : "bg-muted/50 border-border hover:bg-muted hover:text-foreground text-muted-foreground cursor-pointer"
          }
        `}
      >
        {data.isRunning ? "\uC2E4\uD589 \uC911..." : "\uC2E4\uD589"}
      </button>

      {/* 에러 표시 */}
      {data.status === "error" && (
        <p className="text-[9px] text-red-400/80 mt-1 line-clamp-2" title={String(data.error || "")}>
          {String(data.error || "unknown error").slice(0, 60)}
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

// === Edges ===
const EDGES: Edge[] = [
  { id: "e-collect-validate", source: "collect", target: "validate", animated: true, style: { stroke: "#3f3f46" } },
  { id: "e-validate-classify", source: "validate", target: "classify", animated: true, style: { stroke: "#3f3f46" } },
  { id: "e-classify-diagnose", source: "classify", target: "diagnose", animated: true, style: { stroke: "#3f3f46" } },
  { id: "e-diagnose-recommend", source: "diagnose", target: "recommend", animated: true, style: { stroke: "#3f3f46" } },
  { id: "e-recommend-track", source: "recommend", target: "track", animated: true, style: { stroke: "#3f3f46" } },
];

// === Page Component ===
export default function PipelinePage() {
  const [steps, setSteps] = useState<PipelineStep[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [gates, setGates] = useState<Record<string, GateResult>>({});
  const [runningSteps, setRunningSteps] = useState<Set<string>>(new Set());

  // 파이프라인 상태 fetch
  const fetchStatus = useCallback(() => {
    fetch(`/api/pipeline/status`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: PipelineStatusData | null) => {
        if (data?.steps) {
          setSteps(data.steps);
          // 실행 중인 스텝 업데이트
          const running = new Set<string>();
          for (const s of data.steps) {
            if (s.status === "running") running.add(s.step);
          }
          setRunningSteps(running);
        }
      })
      .catch(() => {});
  }, []);

  // 타임라인 fetch
  const fetchTimeline = useCallback(() => {
    fetch(`/api/pipeline/timeline?limit=30`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { events: TimelineEvent[] } | null) => {
        if (data?.events) setTimeline(data.events);
      })
      .catch(() => {});
  }, []);

  // 게이트 fetch
  const fetchGates = useCallback(() => {
    fetch(`/api/gate`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: Record<string, GateResult> | null) => {
        if (data) setGates(data);
      })
      .catch(() => {});
  }, []);

  // 초기 로드 + 10초 자동 새로고침
  useEffect(() => {
    fetchStatus();
    fetchTimeline();
    fetchGates();

    const interval = setInterval(() => {
      fetchStatus();
      fetchTimeline();
    }, 10_000);

    return () => clearInterval(interval);
  }, [fetchStatus, fetchTimeline, fetchGates]);

  // 스텝 실행
  const handleRunStep = useCallback((stepId: string) => {
    setRunningSteps((prev) => new Set([...prev, stepId]));

    fetch(`/api/pipeline/${stepId}/run`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          // 운영자 진단 컨텍스트라 원문을 유지하되, 무엇의 실패인지 한국어로 선행 (F-002)
          alert(`${ERRORS.RUN_FAILED_PREFIX}${data.error}`);
          setRunningSteps((prev) => {
            const next = new Set(prev);
            next.delete(stepId);
            return next;
          });
        }
        // 실행 시작 후 상태 새로고침
        setTimeout(fetchStatus, 1000);
        setTimeout(fetchTimeline, 1000);
      })
      .catch(() => {
        setRunningSteps((prev) => {
          const next = new Set(prev);
          next.delete(stepId);
          return next;
        });
      });
  }, [fetchStatus, fetchTimeline]);

  // 스텝 상태 → 노드 status 변환
  const getNodeStatus = (step: PipelineStep): "ok" | "warning" | "error" | "running" => {
    if (step.status === "running" || runningSteps.has(step.step)) return "running";
    if (step.status === "error") return "error";
    if (step.status === "done") return "ok";
    // idle 상태에서 레코드가 있으면 ok, 없으면 warning
    return step.record_count > 0 ? "ok" : "warning";
  };

  // 파이프라인 노드 정의
  const nodes: Node[] = steps.length > 0
    ? steps.map((s, i) => ({
        id: s.step,
        type: "pipeline",
        position: { x: i * NODE_PITCH_X, y: 80 },
        data: {
          label: s.label,
          sub: s.description,
          status: getNodeStatus(s),
          recordCount: s.record_count,
          lastUpdated: s.last_updated,
          stepId: s.step,
          onRun: handleRunStep,
          isRunning: runningSteps.has(s.step),
          href: STEP_HREFS[s.step],
        } satisfies PipelineNodeData,
      }))
    : DEFAULT_NODES.map((n) => ({
        ...n,
        data: {
          ...n.data,
          onRun: handleRunStep,
          isRunning: false,
        },
      }));

  const nodeTypes = useCallback(
    () => ({ pipeline: PipelineNode }),
    [],
  );

  // 게이트 조건 (collect + validate + regime + recommend)
  const allConditions = Object.entries(gates).flatMap(([, result]) => result.conditions);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Pipeline</h1>
        <div className="flex items-center gap-3">
          {/* 실행 중 카운터 */}
          {runningSteps.size > 0 && (
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-blue-400/10 text-blue-400 text-[10px] font-medium">
              <span className="inline-flex h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
              <span>{runningSteps.size}{PL.RUNNING_SUFFIX}</span>
            </div>
          )}
          {/* 자동 새로고침 표시 */}
          <span className="text-[10px] text-muted-foreground/50">{PL.AUTO_REFRESH}</span>
        </div>
      </div>

      {/* React Flow 캔버스 */}
      <div className="h-80 rounded-xl border border-border bg-background overflow-hidden">
        <ReactFlow
          nodes={nodes}
          edges={EDGES}
          nodeTypes={nodeTypes()}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          proOptions={{ hideAttribution: true }}
          minZoom={0.4}
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
          <span>{PL.LEGEND_OK}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-flex h-2 w-2 rounded-full bg-amber-500" />
          <span>{PL.LEGEND_WARN}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-flex h-2 w-2 rounded-full bg-red-500" />
          <span>{PL.LEGEND_ERROR}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-flex h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
          <span>{PL.LEGEND_RUNNING}</span>
        </div>
      </div>

      {/* ── Event Timeline + Gate Conditions ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 이벤트 타임라인 */}
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground mb-3">{PL.EVENT_TIMELINE}</p>
          {timeline.length === 0 ? (
            <p className="text-xs text-muted-foreground/50 py-6 text-center">
              {PL.NO_EVENTS} &mdash; {PL.RUN_STEP_HINT}
            </p>
          ) : (
            <div className="space-y-1.5 max-h-100 overflow-y-auto">
              {timeline.map((ev, i) => (
                <div key={`${ev.timestamp}-${i}`} className="flex items-start gap-2 text-xs py-1.5 border-b border-border/30 last:border-0">
                  <EventIcon type={ev.event_type} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-foreground/80 capitalize">{ev.step}</span>
                      <span className={`text-[10px] px-1 py-0.5 rounded ${
                        ev.event_type === "success" ? "bg-emerald-500/10 text-emerald-400" :
                        ev.event_type === "error" ? "bg-red-500/10 text-red-400" :
                        "bg-blue-500/10 text-blue-400"
                      }`}>
                        {ev.event_type}
                      </span>
                    </div>
                    {/* #1219: raw JSON.stringify 폴백 폐지 — 사람이 읽는 요약 한 줄 */}
                    {ev.payload && summarizePayload(ev.payload) && (
                      <p className="text-muted-foreground/70 text-[10px] mt-0.5 line-clamp-1">
                        {summarizePayload(ev.payload)}
                      </p>
                    )}
                  </div>
                  <span className="text-[10px] text-muted-foreground/40 shrink-0">
                    {formatTimestamp(ev.timestamp)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Gate Conditions */}
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground mb-3">{PL.GATE_CONDITIONS}</p>
          {allConditions.length === 0 ? (
            <p className="text-xs text-muted-foreground/50 py-6 text-center">
              {PL.GATE_LOADING}
            </p>
          ) : (
            <div className="space-y-1.5 max-h-100 overflow-y-auto">
              {allConditions.map((c) => (
                <div key={c.id} className="flex items-start gap-2 text-xs py-1.5 border-b border-border/30 last:border-0">
                  <span className={`shrink-0 text-sm ${c.passed ? "text-emerald-400" : "text-red-400"}`}>
                    {c.passed ? "\u2713" : "\u2717"}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-foreground/80">{c.description}</p>
                    <p className={`text-[10px] mt-0.5 ${c.passed ? "text-muted-foreground/50" : "text-muted-foreground/70"}`}>
                      {c.detail}
                    </p>
                  </div>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded shrink-0 ${
                    c.passed ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400"
                  }`}>
                    {c.phase}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// === 기본 노드 (API 응답 전) ===
const DEFAULT_NODES: Node[] = [
  {
    id: "collect",
    type: "pipeline",
    position: { x: 0 * NODE_PITCH_X, y: 80 },
    data: { label: "Collect", sub: "15 collectors + 6 sites", status: "warning", recordCount: 0, lastUpdated: null, stepId: "collect", href: "/engine" } as PipelineNodeData,
  },
  {
    id: "validate",
    type: "pipeline",
    position: { x: 1 * NODE_PITCH_X, y: 80 },
    data: { label: "Validate", sub: "Signal backtest + scorecard", status: "warning", recordCount: 0, lastUpdated: null, stepId: "validate", href: "/signals" } as PipelineNodeData,
  },
  {
    id: "classify",
    type: "pipeline",
    position: { x: 2 * NODE_PITCH_X, y: 80 },
    data: { label: "Classify", sub: "6-regime classifier", status: "warning", recordCount: 0, lastUpdated: null, stepId: "classify", href: "/strategy" } as PipelineNodeData,
  },
  {
    id: "diagnose",
    type: "pipeline",
    position: { x: 3 * NODE_PITCH_X, y: 80 },
    data: { label: "Diagnose", sub: "10 agents consensus", status: "warning", recordCount: 0, lastUpdated: null, stepId: "diagnose", href: "/consensus" } as PipelineNodeData,
  },
  {
    id: "recommend",
    type: "pipeline",
    position: { x: 4 * NODE_PITCH_X, y: 80 },
    data: { label: "Recommend", sub: "Buy/sell + price targets", status: "warning", recordCount: 0, lastUpdated: null, stepId: "recommend", href: "/targets" } as PipelineNodeData,
  },
  {
    id: "track",
    type: "pipeline",
    position: { x: 5 * NODE_PITCH_X, y: 80 },
    data: { label: "Track", sub: "30/60/90d outcomes", status: "warning", recordCount: 0, lastUpdated: null, stepId: "track", href: "/targets" } as PipelineNodeData,
  },
];
