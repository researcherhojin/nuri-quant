/**
 * /advisor → /rebalance 리다이렉트 (#1227 U5c).
 *
 * Rebalance Advisor(룰 위반 축)와 Rebalancing(비중 축)은 같은 질문의 두 절반이라
 * /rebalance 한 페이지 두 섹션으로 통합됐다. 북마크·외부 링크 보존용 경로.
 */
import { redirect } from "next/navigation";

export default function AdvisorPage() {
  redirect("/rebalance");
}
