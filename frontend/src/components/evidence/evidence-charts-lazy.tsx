"use client";

/**
 * Evidence 차트 lazy wrapper 5종 — Recharts SSR 경고 회피 (#1225).
 * price-chart-lazy.tsx 와 동일 패턴: dynamic({ ssr: false }) + pulse 스켈레톤.
 */
import nextDynamic from "next/dynamic";

function skeleton(testid: string, heightClass: string) {
  const Skeleton = () => (
    <div className={`${heightClass} bg-card rounded-xl border border-border animate-pulse`} data-testid={testid} />
  );
  Skeleton.displayName = "EvidenceChartSkeleton";
  return Skeleton;
}

export const RegimeChartLazy = nextDynamic(
  () => import("@/components/evidence/regime-chart").then((m) => m.RegimeChart),
  { ssr: false, loading: skeleton("regime-chart-loading", "h-96") },
);

export const PortfolioTreemapLazy = nextDynamic(
  () => import("@/components/evidence/portfolio-treemap").then((m) => m.PortfolioTreemap),
  { ssr: false, loading: skeleton("portfolio-treemap-loading", "h-80") },
);

export const SignalPerformanceChartLazy = nextDynamic(
  () => import("@/components/evidence/signal-performance-chart").then((m) => m.SignalPerformanceChart),
  { ssr: false, loading: skeleton("signal-performance-loading", "h-56") },
);

export const FearGreedChartLazy = nextDynamic(
  () => import("@/components/evidence/fear-greed-chart").then((m) => m.FearGreedChart),
  { ssr: false, loading: skeleton("fear-greed-loading", "h-56") },
);

export const SellEvidenceChartLazy = nextDynamic(
  () => import("@/components/evidence/sell-evidence-chart").then((m) => m.SellEvidenceChart),
  { ssr: false, loading: skeleton("sell-evidence-loading", "h-40") },
);
