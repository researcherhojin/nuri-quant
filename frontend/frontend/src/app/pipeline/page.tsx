"use client";

import { useEffect, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import Link from "next/link";

function PipelineNode({ data }: { data: any }) {
  const statusColor = data.status === "ok"
    ? "bg-emerald-500"
    : data.status === "warning"
    ? "bg-amber-500"
    : data.status === "error"
    ? "bg-red-500"
    : "bg-zinc-600";

  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-xl px-5 py-4 min-w-[180px] shadow-lg hover:border-zinc-500 transition-colors">
      <Handle type="target" position={Position.Left} className="!bg-zinc-600" />
      <div className="flex items-center gap-2 mb-2">
        <span className={`w-2.5 h-2.5 rounded-full ${statusColor}`} />
        <span className="text-lg">{data.icon}</span>
        <span className="text-sm font-semibold text-zinc-100">{data.title}</span>
      </div>
      <p className="text-xs text-zinc-500">{data.sub}</p>
      {data.detail && <p className="text-[10px] text-zinc-600 mt-1.5">{data.detail}</p>}
      {data.href && (
        <Link href={data.href} className="text-[10px] text-emerald-500 hover:text-emerald-400 mt-2 block">
          상세 보기 →
        </Link>
      )}
      <Handle type="source" position={Position.Right} className="!bg-zinc-600" />
    </div>
  );
}

const nodeTypes = { pipeline: PipelineNode };

export default function PipelinePage() {
  const [dashboard, setDashboard] = useState<any>(null);
  const [siege, setSiege] = useState<any>(null);

  useEffect(() => {
    fetch("http://localhost:8001/api/dashboard").then(r => r.json()).then(setDashboard).catch(() => {});
    fetch("http://localhost:8001/api/certify").then(r => r.json()).then(setSiege).catch(() => {});
  }, []);

  const regime = dashboard?.regime?.regime || "loading...";
  const macroScore = dashboard?.macro?.score || 0;
  const gateScore = dashboard?.gate_score || 0;
  const certified = siege?.certified ?? null;
  const siegeScore = siege?.score ?? 0;

  const nodes = [
    { id: "collect", type: "pipeline", position: { x: 0, y: 120 }, data: { icon: "🔍", title: "Collect", sub: "15 collectors + 6 sites", status: "ok", detail: "주가 · 매크로 · 13F · 애널리스트", href: "/portfolio" } },
    { id: "validate", type: "pipeline", position: { x: 260, y: 120 }, data: { icon: "✅", title: "Validate", sub: "3,400+ trades backtest", status: gateScore >= 50 ? "ok" : "warning", detail: `Gate ${gateScore}%`, href: "/signals" } },
    { id: "classify", type: "pipeline", position: { x: 520, y: 120 }, data: { icon: "📊", title: "Classify", sub: "6-regime classifier", status: regime.includes("bear") ? "error" : regime.includes("sideways") ? "warning" : "ok", detail: `${regime} · M${macroScore}`, href: "/strategy" } },
    { id: "diagnose", type: "pipeline", position: { x: 780, y: 120 }, data: { icon: "🤖", title: "7 Agents", sub: "Weighted vote", status: "ok", detail: "Tech·Fund·Macro·Risk·Smart·WS·KR", href: "/consensus" } },
    { id: "certify", type: "pipeline", position: { x: 1040, y: 120 }, data: { icon: "🔒", title: "SIEGE Certify", sub: "10-condition gate", status: certified === true ? "ok" : certified === false ? "error" : "warning", detail: certified !== null ? `${certified ? "CERTIFIED" : "REJECTED"} ${siegeScore}%` : "Loading...", href: "/engine" } },
    { id: "recommend", type: "pipeline", position: { x: 1300, y: 120 }, data: { icon: "📋", title: "Recommend", sub: "Price targets", status: certified ? "ok" : "warning", detail: "매수가 · 손절가 · 익절가", href: "/targets" } },
  ];

  const edges = [
    { id: "e1", source: "collect", target: "validate", animated: true, style: { stroke: "#52525b" } },
    { id: "e2", source: "validate", target: "classify", animated: true, style: { stroke: "#52525b" } },
    { id: "e3", source: "classify", target: "diagnose", animated: true, style: { stroke: "#52525b" } },
    { id: "e4", source: "diagnose", target: "certify", animated: true, style: { stroke: "#52525b" } },
    { id: "e5", source: "certify", target: "recommend", animated: true, style: { stroke: certified ? "#34d399" : "#ef4444" } },
  ];

  return (
    <div>
      <div className="mb-4">
        <h1 className="text-lg font-semibold">Pipeline Flow</h1>
        <p className="text-xs text-zinc-500 mt-1">수집 → 검증 → 분류 → 판단 → 인증 → 추천. 노드 클릭 → 상세.</p>
      </div>
      <div className="h-[400px] rounded-xl border border-zinc-800 overflow-hidden">
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView minZoom={0.5} maxZoom={1.5} proOptions={{ hideAttribution: true }}>
          <Background color="#27272a" gap={20} />
          <Controls />
        </ReactFlow>
      </div>
    </div>
  );
}
