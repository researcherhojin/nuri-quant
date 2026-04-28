"use client";

/**
 * InteractiveBacktestLazy — Recharts SSR warning 제거용 wrapper.
 *
 * strategy/page.tsx 는 server component 라 InteractiveBacktest → EquityCurveChart
 * server-side initial render 에서 ResponsiveContainer 경고. client-only 로 래핑.
 */
import nextDynamic from "next/dynamic";

export interface EquityPoint {
  date: string;
  strategy: number;
  spy: number;
  drawdown: number;
}

export interface BacktestMetrics {
  total_return: number;
  sharpe: number;
  max_drawdown: number;
  win_rate: number;
  spy_total_return: number;
  excess_return: number;
}

const LazyInteractive = nextDynamic(
  () => import("@/components/ui/interactive-backtest").then((m) => m.InteractiveBacktest),
  {
    ssr: false,
    loading: () => (
      <div
        className="h-96 bg-card rounded-xl border border-border animate-pulse"
        data-testid="interactive-backtest-loading"
      />
    ),
  },
);

interface InteractiveBacktestLazyProps {
  initialData: EquityPoint[];
  initialMetrics?: BacktestMetrics;
}

export function InteractiveBacktestLazy(props: InteractiveBacktestLazyProps) {
  return <LazyInteractive {...props} />;
}

