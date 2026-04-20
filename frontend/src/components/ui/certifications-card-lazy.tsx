"use client";

/**
 * CertificationsCardLazy — V2.1 #4 Recharts SSR warning 제거용 wrapper.
 *
 * 문제: Recharts `ResponsiveContainer` 는 서버 렌더 중 DOM 측정을 못 해
 *   `The width(-1) and height(-1) of chart should be greater than 0`
 * 를 stderr 로 로깅. V2 배포 후 production log 에서 확인 (NEXT_SESSION 교훈 #40).
 *
 * 해결: `next/dynamic({ ssr: false })` 는 Client Component 내에서만 사용 가능 →
 * 이 파일이 "use client" 경계 역할. 서버 페이지 (engine/page.tsx) 는 여기서
 * 정적 import 하고, 실제 Recharts 구동은 client mount 이후에만 일어남.
 */
import nextDynamic from "next/dynamic";

import type {
  CertificationsListResponse,
  CertificationsSummary,
} from "@/components/ui/certifications-card";

const LazyCertificationsCard = nextDynamic(
  () => import("@/components/ui/certifications-card").then((m) => m.CertificationsCard),
  {
    ssr: false,
    loading: () => (
      <div className="h-80 bg-card rounded-xl border border-border animate-pulse" />
    ),
  },
);

interface CertificationsCardLazyProps {
  history: CertificationsListResponse;
  summary: CertificationsSummary;
}

export function CertificationsCardLazy(props: CertificationsCardLazyProps) {
  return <LazyCertificationsCard {...props} />;
}
