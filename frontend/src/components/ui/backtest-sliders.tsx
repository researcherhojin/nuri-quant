"use client";

import { useState } from "react";

interface BacktestParams {
  smaPeriod: number;
  lookback: string;
  stopLoss: number;
  takeProfit: number;
}

interface BacktestSlidersProps {
  onRun: (params: BacktestParams) => void;
  initialParams?: BacktestParams;
  loading?: boolean;
}

const LOOKBACKS = ["1Y", "3Y", "5Y"] as const;
const SMA_PERIODS = [50, 100, 200] as const;
const DEFAULT_PARAMS: BacktestParams = {
  smaPeriod: 50,
  lookback: "3Y",
  stopLoss: -7,
  takeProfit: 20,
};

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

export function BacktestSliders({ onRun, initialParams, loading }: BacktestSlidersProps) {
  const [params, setParams] = useState<BacktestParams>(initialParams ?? DEFAULT_PARAMS);

  const update = (key: keyof BacktestParams, value: number | string) =>
    setParams((p) => ({ ...p, [key]: value }));

  const isDefault = params.smaPeriod === DEFAULT_PARAMS.smaPeriod &&
    params.lookback === DEFAULT_PARAMS.lookback &&
    params.stopLoss === DEFAULT_PARAMS.stopLoss &&
    params.takeProfit === DEFAULT_PARAMS.takeProfit;

  return (
    <div className="flex flex-col gap-2 p-3 rounded-lg bg-zinc-900/40 border border-zinc-800/60">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground font-semibold">Backtest Parameters</span>
        <div className="flex items-center gap-1.5">
          {SMA_PERIODS.map((period) => (
            <button
              key={period}
              onClick={() => update("smaPeriod", period)}
              className={`text-[10px] px-1.5 py-0.5 rounded transition-colors ${
                params.smaPeriod === period ? "bg-muted text-zinc-200" : "text-muted-foreground hover:text-zinc-300"
              }`}
            >
              SMA {period}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        <Slider label="Stop" value={params.stopLoss} min={-15} max={-3} step={1} suffix="%" onChange={(v) => update("stopLoss", v)} />
        <Slider label="Take" value={params.takeProfit} min={10} max={40} step={5} suffix="%" onChange={(v) => update("takeProfit", v)} />
      </div>

      <div className="flex items-center gap-1.5">
        {LOOKBACKS.map((lookback) => (
          <button
            key={lookback}
            onClick={() => update("lookback", lookback)}
            className={`text-[10px] px-1.5 py-0.5 rounded transition-colors ${
              params.lookback === lookback ? "bg-muted text-zinc-200" : "text-muted-foreground hover:text-zinc-300"
            }`}
          >
            {lookback}
          </button>
        ))}
      </div>

      <div className="flex items-center justify-between">
        {!isDefault && (
          <button
            onClick={() => setParams(DEFAULT_PARAMS)}
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
