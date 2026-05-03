/**
 * #503 Phase C — macro event → impacted sector mapping.
 *
 * 사용자 holdings 의 sector 가 현재 활성 macro event 의 영향권에 있는지
 * 표시하기 위한 lookup. 단순 keyword 매핑 — 정교한 sector classification
 * 은 §3.10 SAA framework 의 future scope.
 */
import type { MacroEvent } from "@/components/ui/market-context";

// 카테고리 → sector keyword 집합. holding.sector 가 한국어 / ETF prefix 포함이라
// substring 매칭으로 검사한다 (e.g., "ETF/USIndex" 는 "Index" 를 contain).
const CATEGORY_SECTORS: Record<string, string[]> = {
  oil_supply_shock: ["Energy", "Oil"],
  geopolitical_escalation: ["Energy", "Defense", "Aero"],
  geopolitical_de_escalation: ["Energy", "Defense", "Aero"],
  trade_war: ["Semi", "Industrial", "Tech"],
  fed_dovish: ["Tech", "Growth", "Semi"],
  fed_hawkish: ["Bank", "Financial", "Bond"],
  sector_rally: [], // ticker-specific, sector-agnostic
  earnings_beat: [],
  earnings_miss: [],
};

/**
 * 활성 macro event 들이 영향을 주는 sector keyword 의 lower-case Set.
 * 24h 내 confidence ≥ 0.6 이벤트만 본다 — 너무 오래된 / 약한 이벤트는
 * holdings 행 매 줄에 macro 뱃지를 띄우면 노이즈가 된다.
 */
export function getMacroImpactedSectors(events: MacroEvent[]): Set<string> {
  const result = new Set<string>();
  const cutoff = Date.now() - 24 * 60 * 60 * 1000;
  for (const ev of events) {
    if ((ev.confidence ?? 0) < 0.6) continue;
    const ts = Date.parse(ev.published_at);
    if (!Number.isFinite(ts) || ts < cutoff) continue;
    const sectors = CATEGORY_SECTORS[ev.category] ?? [];
    for (const s of sectors) result.add(s.toLowerCase());
  }
  return result;
}

/** holding.sector 문자열이 impacted set 에 포함되는지 substring 검사. */
export function isMacroAware(sector: string | null | undefined, impacted: Set<string>): boolean {
  if (!sector || impacted.size === 0) return false;
  const low = sector.toLowerCase();
  for (const keyword of impacted) {
    if (low.includes(keyword)) return true;
  }
  return false;
}
