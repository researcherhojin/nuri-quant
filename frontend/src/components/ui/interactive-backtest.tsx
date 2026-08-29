"use client";

import { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
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
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const hasInteractiveParams = searchParams.has("sma") || searchParams.has("lb") || searchParams.has("sl") || searchParams.has("tp");
  const [data, setData] = useState<EquityPoint[]>(initialData);
  const [metrics, setMetrics] = useState<BacktestMetrics | undefined>(initialMetrics);
  const [loading, setLoading] = useState(false);
  const [isCustom, setIsCustom] = useState(hasInteractiveParams);
  const [mode, setMode] = useState<"static" | "interactive">(hasInteractiveParams ? "interactive" : "static");

  const initialParams = {
    smaPeriod: Number(searchParams.get("sma") ?? "50"),
    lookback: searchParams.get("lb") ?? "3Y",
    stopLoss: Number(searchParams.get("sl") ?? "-7"),
    takeProfit: Number(searchParams.get("tp") ?? "20"),
  };

  const runBacktest = async (params: { smaPeriod: number; lookback: string; stopLoss: number; takeProfit: number }) => {
    setLoading(true);
    try {
      const query = new URLSearchParams({
        sma: String(params.smaPeriod),
        lb: params.lookback,
        sl: String(params.stopLoss),
        tp: String(params.takeProfit),
      });
      const res = await fetch(`/api/backtest/equity?sma=${params.smaPeriod}&period=${params.lookback}&sl=${params.stopLoss}&tp=${params.takeProfit}`);
      if (res.ok) {
        const result = await res.json();
        if (result.equity?.length > 0) {
          setData(result.equity);
          setMetrics(result.metrics);
          setIsCustom(true);
          setMode("interactive");
          router.replace(`${pathname}?${query.toString()}`);
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
      <div className="flex items-center gap-1.5">
        <button
          onClick={() => setMode("static")}
          className={`text-[10px] px-2 py-0.5 rounded-sm transition-colors ${
            mode === "static" ? "bg-muted text-zinc-200" : "text-muted-foreground hover:text-zinc-300"
          }`}
        >
          Static
        </button>
        <button
          onClick={() => setMode("interactive")}
          className={`text-[10px] px-2 py-0.5 rounded-sm transition-colors ${
            mode === "interactive" ? "bg-muted text-zinc-200" : "text-muted-foreground hover:text-zinc-300"
          }`}
        >
          Interactive
        </button>
      </div>

      {mode === "interactive" && (
        <BacktestSliders onRun={runBacktest} initialParams={initialParams} loading={loading} />
      )}

      {(mode === "static" ? initialMetrics : metrics) && (
        <div className="flex gap-3 text-[10px]">
          <span className={(mode === "static" ? initialMetrics : metrics)!.total_return >= 0 ? "text-emerald-400" : "text-red-400"}>
            Return {(mode === "static" ? initialMetrics : metrics)!.total_return > 0 ? "+" : ""}{(mode === "static" ? initialMetrics : metrics)!.total_return}%
          </span>
          <span className="text-zinc-400">Sharpe {(mode === "static" ? initialMetrics : metrics)!.sharpe}</span>
          <span className="text-red-400">MDD {(mode === "static" ? initialMetrics : metrics)!.max_drawdown}%</span>
          <span className="text-zinc-400">Win {((mode === "static" ? initialMetrics : metrics)!.win_rate * 100).toFixed(0)}%</span>
          <span className={(mode === "static" ? initialMetrics : metrics)!.excess_return >= 0 ? "text-emerald-500" : "text-red-500"}>
            vs SPY {(mode === "static" ? initialMetrics : metrics)!.excess_return > 0 ? "+" : ""}{(mode === "static" ? initialMetrics : metrics)!.excess_return}%
          </span>
          {mode === "interactive" && isCustom && <span className="text-amber-400 ml-auto">Custom params</span>}
        </div>
      )}

      <EquityCurveChart data={mode === "static" ? initialData : data} />
    </div>
  );
}
