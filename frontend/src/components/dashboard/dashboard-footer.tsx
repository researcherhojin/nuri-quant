/**
 * DashboardFooter (#1204 U2a) — 품질 + freshness + 파이프라인 푸터. page.tsx 에서 추출, 동작 불변.
 */
import Link from "next/link";
import { FreshnessBar, type FreshnessItem } from "@/components/ui/freshness-bar";
import { FOOTER } from "@/lib/strings";
import { pipelineStatusColors } from "./helpers";

export interface FooterCondition {
  passed: boolean;
  severity?: string;
  description?: string;
  detail?: string;
  [key: string]: unknown;
}

interface DashboardFooterProps {
  siegeTotal: number;
  siegePassed: number;
  siegeFailed: FooterCondition[];
  advisorViolations: number;
  /** 원본 게이트 보존: items=[] 이고 details 만 있어도 빈 바를 렌더하던 동작 그대로 */
  showFreshness: boolean;
  freshnessItems: FreshnessItem[];
  pipelineSteps: Array<{ step: string; label: string; status: string; record_count: number; last_updated: string | null }>;
}

export function DashboardFooter({
  siegeTotal, siegePassed, siegeFailed, advisorViolations, showFreshness, freshnessItems, pipelineSteps,
}: DashboardFooterProps) {
  return (
    <div className="mt-auto pt-2 border-t border-zinc-800/60 space-y-1">
      <div className="flex items-center gap-3 flex-wrap text-[10px]">
        {siegeTotal > 0 && siegeFailed.length === 0 && (
          <span className="text-zinc-400"><span className="text-emerald-500">&#10003;</span> {FOOTER.QUALITY} {siegePassed}/{siegeTotal}</span>
        )}
        {siegeTotal > 0 && siegeFailed.length > 0 && (
          <span className="text-red-400"><span className="text-red-500">&#10007;</span> {FOOTER.QUALITY_FAIL} {siegeFailed.length}{FOOTER.COUNT_SUFFIX}</span>
        )}
        {advisorViolations > 0 && (
          <span className="text-red-400">{FOOTER.RULE_VIOLATION} {advisorViolations}{FOOTER.COUNT_SUFFIX}</span>
        )}
        {/* upcoming events moved to sidebar (#214). Footer keeps quality/violations/freshness. */}
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
      {siegeTotal > 0 && siegeFailed.length > 0 && (
        <div className="space-y-0.5">
          {siegeFailed.slice(0, 2).map((c: FooterCondition, i: number) => (
            <p key={i} className="text-[10px] text-zinc-400 pl-3">
              <span className={c.severity === "error" ? "text-red-400" : "text-amber-400"}>{c.severity === "error" ? "✖" : "△"}</span>{" "}
              {c.description} &mdash; <span className="text-zinc-600">{c.detail}</span>
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
