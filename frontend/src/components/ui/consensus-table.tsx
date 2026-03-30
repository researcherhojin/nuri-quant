"use client";

/**
 * ConsensusTable — 10-Agent 합의 테이블 + 확장 가능한 에이전트 reasoning.
 *
 * 행 클릭 → 10개 에이전트의 개별 verdict, confidence, reasoning 표시.
 */
import { Fragment, useState } from "react";
import { StatusBadge } from "./status-badge";

interface AgentVerdict {
  agent_name: string;
  ticker: string;
  action: string;
  confidence: number;
  reasoning: string;
  data_points: Record<string, any>;
}

interface ConsensusRow {
  ticker: string;
  final_action: string;
  final_confidence: number;
  agreement_rate: number;
  verdicts: AgentVerdict[];
  dissent: string[];
  reasoning: string;
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

export function ConsensusTable({ data }: { data: ConsensusRow[] }) {
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
                  <td className="py-1.5 px-2 text-center"><StatusBadge status={row.final_action} size="md" /></td>
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
                      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                        {AGENT_ORDER.map((a) => {
                          const v = agentMap[a.key];
                          if (!v) return null;
                          return (
                            <div key={a.key} className="bg-muted/30 rounded-md p-2 border border-border/30">
                              <div className="flex items-center gap-2 mb-1">
                                <span className="text-[10px] font-medium text-muted-foreground">{a.label}</span>
                                <StatusBadge status={v.action} size="sm" />
                                <span className="text-[10px] text-muted-foreground ml-auto">{v.confidence.toFixed(0)}%</span>
                              </div>
                              <p className="text-[10px] text-muted-foreground/80 leading-tight">{v.reasoning}</p>
                            </div>
                          );
                        })}
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
