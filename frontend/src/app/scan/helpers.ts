/**
 * Scan 페이지 병합 헬퍼 (#1219 U4b).
 *
 * Market Scanner(top-N)와 Swing Entries 는 같은 스캔에서 갈라진 두 뷰라
 * 15/20 행이 중복 렌더됐다 (2026-08-25 실측). ticker 기준 union 으로 한
 * 테이블에 합친다 — 스캔 쪽 모멘텀 필드(1D/5D/RSI)와 스윙 쪽 에이전트
 * 판정(action/conf/승인/사유)을 병기하고, 한쪽에만 있는 행은 없는 필드를
 * null 로 둔다 (렌더는 —).
 */

export interface ScanResult {
  ticker: string; price: number; change_1d: number; change_5d: number;
  volume_ratio: number; rsi: number; signal: string; score: number;
}

export interface SwingEntry {
  ticker: string; price: number; scan_signal: string; scan_score: number;
  agent_action: string; agent_confidence: number; approved: boolean; reason: string;
}

export interface MergedScanRow {
  ticker: string;
  price: number | null;
  change_1d: number | null;
  change_5d: number | null;
  rsi: number | null;
  signal: string | null;
  score: number | null;
  agent_action: string | null;
  agent_confidence: number | null;
  /** null = 스윙 평가 자체가 없음 (스캔 전용 행) */
  approved: boolean | null;
  reason: string | null;
}

export function mergeScanSwing(scan: ScanResult[], swing: SwingEntry[]): MergedScanRow[] {
  const bySwing = new Map(swing.map((e) => [e.ticker, e]));
  const seen = new Set<string>();
  const rows: MergedScanRow[] = [];

  // 스캔 순서(스코어 내림차순, API 정렬) 우선 — 스윙 필드를 조인
  for (const r of scan) {
    const sw = bySwing.get(r.ticker);
    seen.add(r.ticker);
    rows.push({
      ticker: r.ticker,
      price: r.price ?? sw?.price ?? null,
      change_1d: r.change_1d ?? null,
      change_5d: r.change_5d ?? null,
      rsi: r.rsi ?? null,
      signal: r.signal ?? sw?.scan_signal ?? null,
      score: r.score ?? sw?.scan_score ?? null,
      agent_action: sw?.agent_action ?? null,
      agent_confidence: sw?.agent_confidence ?? null,
      approved: sw ? sw.approved : null,
      reason: sw?.reason ?? null,
    });
  }

  // 스윙 전용 행 (top-N 밖) — 스캔 모멘텀 필드는 없음
  for (const sw of swing) {
    if (seen.has(sw.ticker)) continue;
    rows.push({
      ticker: sw.ticker,
      price: sw.price ?? null,
      change_1d: null,
      change_5d: null,
      rsi: null,
      signal: sw.scan_signal ?? null,
      score: sw.scan_score ?? null,
      agent_action: sw.agent_action ?? null,
      agent_confidence: sw.agent_confidence ?? null,
      approved: sw.approved,
      reason: sw.reason ?? null,
    });
  }
  return rows;
}
