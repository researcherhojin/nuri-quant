/**
 * DashboardFooter (#1204 U2a) — 규칙 위반 + freshness + 파이프라인 푸터. page.tsx 에서 추출.
 * #1619: SIEGE 품질 줄(통과/미통과 + 실패 조건 2건)은 인증 UI 철거와 함께 제거.
 */
import Link from "next/link";
import { FreshnessBar, type FreshnessItem } from "@/components/ui/freshness-bar";
import { FOOTER } from "@/lib/strings";
import { pipelineStatusColors } from "./helpers";

interface DashboardFooterProps {
  advisorViolations: number;
  /** 원본 게이트 보존: items=[] 이고 details 만 있어도 빈 바를 렌더하던 동작 그대로 */
  showFreshness: boolean;
  freshnessItems: FreshnessItem[];
  pipelineSteps: Array<{ step: string; label: string; status: string; record_count: number; last_updated: string | null }>;
}

export function DashboardFooter({
  advisorViolations, showFreshness, freshnessItems, pipelineSteps,
}: DashboardFooterProps) {
  return (
    <div className="mt-auto pt-2 border-t border-zinc-800/60 space-y-1">
      <div className="flex items-center gap-3 flex-wrap text-[10px]">
        {advisorViolations > 0 && (
          <span className="text-red-400">{FOOTER.RULE_VIOLATION} {advisorViolations}{FOOTER.COUNT_SUFFIX}</span>
        )}
        {/* upcoming events moved to sidebar (#214). Footer keeps violations/freshness. */}
        <div className="ml-auto flex items-center gap-2">
          {showFreshness && <FreshnessBar items={freshnessItems} />}
          {pipelineSteps.length > 0 && (
            <div className="flex items-center gap-0.5">
              {pipelineSteps.map((s) => (
                <span key={s.step} className={`inline-flex size-1.5 rounded-full ${pipelineStatusColors[s.status] || "bg-zinc-500"}`} title={`${s.label}: ${s.record_count.toLocaleString()}건`} />
              ))}
              <Link href="/pipeline" className="text-[9px] text-zinc-600 hover:text-zinc-400 ml-0.5">&rarr;</Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
