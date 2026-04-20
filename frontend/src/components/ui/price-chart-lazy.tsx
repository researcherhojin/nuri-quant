"use client";

/**
 * PriceChartLazy — Recharts SSR warning 제거용 wrapper.
 *
 * ticker/[symbol]/page.tsx 는 server component 라 PriceChart server-side initial
 * render 에서 ResponsiveContainer 경고. dynamic({ ssr: false }) 로 client-only.
 */
import nextDynamic from "next/dynamic";

import type { PriceData } from "@/components/ui/price-chart";

const LazyChart = nextDynamic(
  () => import("@/components/ui/price-chart").then((m) => m.PriceChart),
  {
    ssr: false,
    loading: () => (
      <div
        className="h-80 bg-card rounded-xl border border-border animate-pulse"
        data-testid="price-chart-loading"
      />
    ),
  },
);

interface PriceChartLazyProps {
  data: PriceData[];
  ticker: string;
}

export function PriceChartLazy(props: PriceChartLazyProps) {
  return <LazyChart {...props} />;
}

export type { PriceData };
