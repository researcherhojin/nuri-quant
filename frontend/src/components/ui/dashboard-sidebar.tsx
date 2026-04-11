/**
 * DashboardSidebar — 우측 사이드바 (Phase 2-D #214)
 *
 * wide 화면(lg+)에서 보유 종목 테이블 옆에 배치되는 컨텍스트 패널 4개:
 *   1. ⚠ 알림       — risk first (STRATEGY.md §2.4 observability)
 *   2. 📅 다음 이벤트 — 14일 이내 실적/FOMC/macro
 *   3. 🎯 신규 매수 후보 (compact) — 보유 외 BUY 신호
 *   4. 📊 시장 mini   — SPY/QQQ/VIX 한 줄 요약
 *
 * 좁은 화면에서는 page.tsx 쪽에서 stack 처리. 이 컴포넌트 자체는 항상 pure render.
 */
import Link from "next/link";

// ── Panel shapes ─────────────────────────────────────────────
export interface SidebarAlert {
  level: string;
  message: string;
  href: string;
}

export interface SidebarEvent {
  date: string;
  description?: string;
  ticker?: string | null;
}

export interface SidebarCandidate {
  action: string;
  ticker: string;
  name?: string | null;
  account?: string;
  confidence: number;
}

export interface SidebarMarketIndex {
  ticker: string;
  label: string;
  changePct?: number | null;
  value?: number | null;
  tone?: "positive" | "negative" | "neutral";
}

export interface DashboardSidebarProps {
  alerts: SidebarAlert[];
  events: SidebarEvent[];
  candidates: SidebarCandidate[];
  marketIndexes?: SidebarMarketIndex[];
  pensionCandidatesCount?: number;
  isMonthEnd?: boolean;
}

// ── Helpers ──────────────────────────────────────────────────
function formatEventDate(iso: string): string {
  // "2026-04-22" → "04-22"
  if (!iso || iso.length < 10) return iso ?? "";
  return iso.slice(5, 10);
}

function changeTone(change: number | null | undefined): string {
  if (change == null) return "text-zinc-500";
  if (change > 0) return "text-emerald-400";
  if (change < 0) return "text-red-400";
  return "text-zinc-500";
}

function formatChange(change: number | null | undefined): string {
  if (change == null) return "—";
  return `${change >= 0 ? "+" : ""}${change.toFixed(1)}%`;
}

// ── Component ────────────────────────────────────────────────
export function DashboardSidebar({
  alerts,
  events,
  candidates,
  marketIndexes = [],
  pensionCandidatesCount = 0,
  isMonthEnd = false,
}: DashboardSidebarProps) {
  return (
    <aside
      className="flex flex-col gap-3 text-xs"
      data-testid="dashboard-sidebar"
      aria-label="대시보드 사이드바"
    >
      {/* ═══ 1. 알림 ═══ */}
      <section data-testid="sidebar-alerts">
        <h3 className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wider mb-1">
          ⚠ 알림 {alerts.length > 0 && <span className="text-red-400">{alerts.length}</span>}
        </h3>
        {alerts.length === 0 ? (
          <p className="text-[10px] text-zinc-600 px-1">위험 없음</p>
        ) : (
          <div className="space-y-0.5">
            {alerts.map((a, i) => (
              <Link
                key={i}
                href={a.href}
                className="flex items-center gap-1.5 text-[10px] hover:bg-red-950/30 rounded px-1 py-0.5 -mx-1 transition-colors group"
              >
                <span className={a.level === "critical" ? "text-red-400" : "text-amber-400"}>
                  {a.level === "critical" ? "\u2716" : "\u25B3"}
                </span>
                <span className="text-zinc-300 group-hover:text-zinc-100 truncate">
                  {a.message}
                </span>
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* ═══ 2. 다음 이벤트 ═══ */}
      <section data-testid="sidebar-events">
        <h3 className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wider mb-1">
          📅 다음 이벤트
        </h3>
        {events.length === 0 ? (
          <p className="text-[10px] text-zinc-600 px-1">예정된 이벤트 없음</p>
        ) : (
          <div className="space-y-0.5">
            {events.slice(0, 5).map((ev, i) => (
              <div
                key={`${ev.date}-${ev.ticker ?? "macro"}-${i}`}
                className="flex items-center gap-2 text-[10px] text-zinc-400 px-1"
              >
                <span className="text-zinc-600 tabular-nums w-10 shrink-0">{formatEventDate(ev.date)}</span>
                <span className="truncate">{ev.description || ev.ticker || "이벤트"}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ═══ 3. 신규 매수 후보 (compact) ═══ */}
      <section data-testid="sidebar-candidates">
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wider">
            🎯 신규 매수 후보
          </h3>
          <Link href="/decisions" className="text-[9px] text-zinc-600 hover:text-zinc-400">
            기록 →
          </Link>
        </div>
        {candidates.length === 0 ? (
          <p className="text-[10px] text-zinc-600 px-1">
            {pensionCandidatesCount > 0 && !isMonthEnd
              ? `연금 ${pensionCandidatesCount}건 — 월말 매수 대기`
              : "신규 후보 없음"}
          </p>
        ) : (
          <div className="space-y-0.5">
            {candidates.slice(0, 5).map((c, i) => (
              <Link
                key={`${c.ticker}-${i}`}
                href={`/ticker/${c.ticker}`}
                className={`flex items-center gap-1.5 text-[10px] px-1 py-0.5 rounded hover:bg-zinc-800/50 border-l-2 ${
                  c.action === "BUY" ? "border-emerald-500" : "border-red-500"
                }`}
              >
                {c.account && (
                  <span className="text-[9px] text-zinc-600 shrink-0" data-testid="candidate-account">
                    {c.account}
                  </span>
                )}
                <span className="text-zinc-100 truncate flex-1">{c.name || c.ticker}</span>
                {c.name && <span className="text-[9px] text-zinc-600 shrink-0">{c.ticker}</span>}
                <span
                  className={`tabular-nums font-bold shrink-0 ${
                    c.confidence >= 80
                      ? "text-emerald-400"
                      : c.confidence >= 50
                      ? "text-amber-400"
                      : "text-red-400"
                  }`}
                >
                  {c.confidence}
                </span>
              </Link>
            ))}
            {pensionCandidatesCount > 0 && !isMonthEnd && (
              <p className="text-[9px] text-zinc-600 px-1 pt-0.5">
                연금 {pensionCandidatesCount}건 — 월말 매수 대기
              </p>
            )}
          </div>
        )}
      </section>

      {/* ═══ 4. 시장 mini ═══ */}
      {marketIndexes.length > 0 && (
        <section data-testid="sidebar-market">
          <h3 className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wider mb-1">
            📊 시장
          </h3>
          <div className="space-y-0.5">
            {marketIndexes.map((m) => (
              <div
                key={m.ticker}
                className="flex items-center justify-between text-[10px] text-zinc-400 px-1"
              >
                <span className="truncate">{m.label}</span>
                <span className={`tabular-nums shrink-0 ${changeTone(m.changePct)}`}>
                  {formatChange(m.changePct)}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </aside>
  );
}
