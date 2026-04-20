"use client";

/**
 * CompositionSectionLazy — dashboard `/` 의 CompositionSection 을 client-only
 * 로 lazy load. Recharts ResponsiveContainer 가 server-side initial render 에서
 * width(-1) 경고를 내는 것을 방지.
 *
 * 주의: CompositionSection 자체는 server component 로 남겨 기존 vitest 는 그대로
 * 동작 (donut 렌더 검증). 이 wrapper 는 page.tsx 에서만 사용.
 */
import nextDynamic from "next/dynamic";

import type { HoldingsSummary } from "@/lib/holdings-summary";
import type { CompositionTab } from "@/components/ui/composition-section";

const LazySection = nextDynamic(
  () => import("@/components/ui/composition-section").then((m) => m.CompositionSection),
  {
    ssr: false,
    loading: () => (
      <div
        className="h-120 bg-card rounded-xl border border-border animate-pulse"
        data-testid="composition-section-loading"
      />
    ),
  },
);

interface CompositionSectionLazyProps {
  summary: HoldingsSummary;
  totalUsd: number;
  activeTab: CompositionTab;
}

export function CompositionSectionLazy(props: CompositionSectionLazyProps) {
  return <LazySection {...props} />;
}

export { parseCompositionTab } from "@/components/ui/composition-section";
export type { CompositionTab } from "@/components/ui/composition-section";
