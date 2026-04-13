"use client";

import { useState } from "react";
import { EquityCurveChart } from "@/components/ui/equity-curve-chart";
import { BacktestSliders } from "@/components/ui/backtest-sliders";

interface EquityPoint {
  date: string;
  strategy: number;
  spy: number;
  drawdown: number;
}

interface BacktestMetrics {
  total_return: number;
  sharpe: number;
  max_drawdown: number;
  win_rate: number;
  spy_total_return: number;
  excess_return: number;
}

interface InteractiveBacktestProps {
  initialData: EquityPoint[];
  initialMetrics?: BacktestMetrics;
}

export function InteractiveBacktest({ initialData, initialMetrics }: InteractiveBacktestProps) {
  const [data, setData] = useState<EquityPoint[]>(initialData);
  const [metrics, setMetrics] = useState<BacktestMetrics | undefined>(initialMetrics);
  const [loading, setLoading] = useState(false);
  const [isCustom, setIsCustom] = useState(false);

  const runBacktest = async (params: { stopLoss: number; takeProfit1: number; takeProfit2: number; trailing: number; period: string }) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/backtest/equity?sl=${params.stopLoss}&tp1=${params.takeProfit1}&tp2=${params.takeProfit2}&trail=${params.trailing}&period=${params.period}`);
      if (res.ok) {
        const result = await res.json();
        if (result.equity?.length > 0) {
          setData(result.equity);
          setMetrics(result.metrics);
          setIsCustom(true);
        }
      }
    } catch {
      // silent — keep current data
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <BacktestSliders onRun={runBacktest} loading={loading} />

      {metrics && (
        <div className="flex gap-3 text-[10px]">
          <span className={metrics.total_return >= 0 ? "text-emerald-400" : "text-red-400"}>
            Return {metrics.total_return > 0 ? "+" : ""}{metrics.total_return}%
          </span>
          <span className="text-zinc-400">Sharpe {metrics.sharpe}</span>
          <span className="text-red-400">MDD {metrics.max_drawdown}%</span>
          <span className="text-zinc-400">Win {(metrics.win_rate * 100).toFixed(0)}%</span>
          <span className={metrics.excess_return >= 0 ? "text-emerald-500" : "text-red-500"}>
            vs SPY {metrics.excess_return > 0 ? "+" : ""}{metrics.excess_return}%
          </span>
          {isCustom && <span className="text-amber-400 ml-auto">Custom params</span>}
        </div>
      )}

      <EquityCurveChart data={data} />
    </div>
  );
}
