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

// === Types ===
interface DashboardData {
  regime?: { regime?: string; label?: string };
  macro?: { score?: number };
  gate?: { ready?: boolean };
  gate_score?: number;
}

interface CertifyData {
  certified?: boolean;
  score?: number;
}

interface PipelineNodeData {
  label: string;
  sub: string;
  status: "ok" | "warning" | "error";
  href?: string;
  [key: string]: any;
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

// === Custom Node Component ===
const PipelineNode = memo(({ data }: { data: PipelineNodeData }) => {
  const status = data.status || "ok";

  return (
    <div
      className={`
        relative bg-zinc-900 border rounded-xl px-6 py-5 min-w-[220px]
        cursor-pointer transition-all duration-200
        hover:bg-zinc-800/80 hover:scale-[1.02]
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
        className="!bg-zinc-600 !border-zinc-500 !w-2 !h-2"
      />

      {/* 상태 표시 */}
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
      <p className="text-base font-bold text-zinc-100 mb-0.5">
        {data.label.split(" ").slice(1).join(" ")}
      </p>

      {/* 부제 */}
      <p className="text-xs text-zinc-500">{data.sub}</p>

      {/* 출력 핸들 */}
      <Handle
        type="source"
        position={Position.Right}
        className="!bg-zinc-600 !border-zinc-500 !w-2 !h-2"
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
  { id: "e-diagnose-certify", source: "diagnose", target: "certify", animated: true, style: { stroke: "#3f3f46" } },
  { id: "e-certify-recommend", source: "certify", target: "recommend", animated: true, style: { stroke: "#3f3f46" } },
];

// === Page Component ===
export default function PipelinePage() {
  const [regime, setRegime] = useState<string>("loading");
  const [certified, setCertified] = useState<boolean | null>(null);
  const [siegeScore, setSiegeScore] = useState<number | null>(null);
  const [gateReady, setGateReady] = useState<boolean | null>(null);

  // API에서 실시간 상태 조회
  useEffect(() => {
    // 대시보드 데이터 (regime, macro, gate)
    fetch("http://localhost:8001/api/dashboard")
      .then((r) => (r.ok ? r.json() : null))
      .then((data: DashboardData | null) => {
        if (data) {
          setRegime(data.regime?.regime || data.regime?.label || "unknown");
          setGateReady(data.gate_score ? data.gate_score >= 50 : null);
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
        }
      })
      .catch(() => setCertified(false));
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

  // 파이프라인 노드 정의
  const nodes: Node[] = [
    {
      id: "collect",
      type: "pipeline",
      position: { x: 0, y: 80 },
      data: { label: "🔍 Collect", sub: "15 collectors + 6 sites", status: gateStatus(), href: "/engine" },
    },
    {
      id: "validate",
      type: "pipeline",
      position: { x: 320, y: 80 },
      data: { label: "✅ Validate", sub: "3,400+ trades backtested", status: "ok", href: "/signals" },
    },
    {
      id: "classify",
      type: "pipeline",
      position: { x: 640, y: 80 },
      data: { label: "📊 Classify", sub: `6 regimes — ${regime}`, status: regimeStatus(), href: "/strategy" },
    },
    {
      id: "diagnose",
      type: "pipeline",
      position: { x: 960, y: 80 },
      data: { label: "🤖 Diagnose", sub: "7 agents consensus", status: "ok", href: "/consensus" },
    },
    {
      id: "certify",
      type: "pipeline",
      position: { x: 1280, y: 80 },
      data: {
        label: "🔒 Certify",
        sub: `SIEGE 10-cond${siegeScore !== null ? ` — ${siegeScore}%` : ""}`,
        status: certified === null ? "warning" : certified ? "ok" : "error",
        href: "/engine",
      },
    },
    {
      id: "recommend",
      type: "pipeline",
      position: { x: 1600, y: 80 },
      data: { label: "📋 Recommend", sub: "price targets + actions", status: "ok", href: "/targets" },
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
            <span className="text-zinc-500">Regime</span>
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
              <span>{certified ? "🛡 CERTIFIED" : "⚠ REJECTED"}</span>
              {siegeScore !== null && (
                <span className="opacity-60">{siegeScore}%</span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* React Flow 캔버스 */}
      <div className="h-[500px] rounded-xl border border-zinc-800 bg-zinc-950 overflow-hidden">
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
            className="!bg-zinc-900 !border-zinc-700 !shadow-lg [&>button]:!bg-zinc-800 [&>button]:!border-zinc-700 [&>button]:!text-zinc-400 [&>button:hover]:!bg-zinc-700"
          />
        </ReactFlow>
      </div>

      {/* 하단 범례 */}
      <div className="flex items-center gap-6 text-[10px] text-zinc-500">
        <div className="flex items-center gap-1.5">
          <span className="inline-flex h-2 w-2 rounded-full bg-emerald-500" />
          <span>Healthy</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-flex h-2 w-2 rounded-full bg-amber-500" />
          <span>Warning / Loading</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-flex h-2 w-2 rounded-full bg-red-500" />
          <span>Error / Failed</span>
        </div>
        <span className="text-zinc-700">|</span>
        <span>Click a node to navigate to its detail page</span>
      </div>
    </div>
  );
}
