"use client";

import { useState } from "react";

interface BacktestParams {
  stopLoss: number;
  takeProfit1: number;
  takeProfit2: number;
  trailing: number;
  period: string;
}

interface BacktestSlidersProps {
  onRun: (params: BacktestParams) => void;
  loading?: boolean;
}

const PERIODS = ["1Y", "3Y", "5Y"] as const;

function Slider({ label, value, min, max, step, suffix, onChange }: {
  label: string; value: number; min: number; max: number; step: number; suffix: string;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="text-[10px] text-muted-foreground w-12 shrink-0">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="flex-1 h-1 accent-emerald-500 cursor-pointer"
      />
      <span className="text-[10px] text-zinc-300 tabular-nums w-10 text-right">{value}{suffix}</span>
    </div>
  );
}

export function BacktestSliders({ onRun, loading }: BacktestSlidersProps) {
  const [params, setParams] = useState<BacktestParams>({
    stopLoss: -7,
    takeProfit1: 20,
    takeProfit2: 40,
    trailing: -15,
    period: "3Y",
  });

  const update = (key: keyof BacktestParams, value: number | string) =>
    setParams((p) => ({ ...p, [key]: value }));

  const isDefault = params.stopLoss === -7 && params.takeProfit1 === 20 &&
    params.takeProfit2 === 40 && params.trailing === -15 && params.period === "3Y";

  return (
    <div className="flex flex-col gap-2 p-3 rounded-lg bg-zinc-900/40 border border-zinc-800/60">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground font-semibold">Backtest Parameters</span>
        <div className="flex items-center gap-1.5">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => update("period", p)}
              className={`text-[10px] px-1.5 py-0.5 rounded transition-colors ${
                params.period === p ? "bg-muted text-zinc-200" : "text-muted-foreground hover:text-zinc-300"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        <Slider label="Stop" value={params.stopLoss} min={-15} max={-3} step={1} suffix="%" onChange={(v) => update("stopLoss", v)} />
        <Slider label="TP1" value={params.takeProfit1} min={10} max={30} step={5} suffix="%" onChange={(v) => update("takeProfit1", v)} />
        <Slider label="Trail" value={params.trailing} min={-20} max={-10} step={1} suffix="%" onChange={(v) => update("trailing", v)} />
        <Slider label="TP2" value={params.takeProfit2} min={20} max={60} step={5} suffix="%" onChange={(v) => update("takeProfit2", v)} />
      </div>

      <div className="flex items-center justify-between">
        {!isDefault && (
          <button
            onClick={() => setParams({ stopLoss: -7, takeProfit1: 20, takeProfit2: 40, trailing: -15, period: "3Y" })}
            className="text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            Reset defaults
          </button>
        )}
        <button
          onClick={() => onRun(params)}
          disabled={loading}
          className="ml-auto text-[10px] px-3 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-medium transition-colors disabled:opacity-50"
        >
          {loading ? "Running..." : "Run Backtest"}
        </button>
      </div>
    </div>
  );
}
