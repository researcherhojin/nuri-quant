"use client";

/**
 * CommandPalette — Cmd-K / Ctrl-K 팔레트 (#1226 U5b).
 *
 * 경량 수제 (cmdk 의존성 없음): 라우트 점프(NAV_GROUPS 단일 소스) +
 * 티커 검색(/api/tickers/search 재사용 — explore 검색과 동일 계약) → /ticker/[symbol].
 * 헤더 트리거 버튼과 모달을 한 컴포넌트로 묶는다 — 모달은 fixed 라 DOM 위치 무관.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";

import { NAV_GROUPS } from "@/components/ui/sidebar";
import { PALETTE } from "@/lib/strings";

export interface PaletteRoute {
  href: string;
  label: string;
  group: string;
}

export interface TickerResult {
  ticker: string;
  name: string | null;
  price: number | null;
}

export type PaletteItem =
  | { kind: "route"; route: PaletteRoute }
  | { kind: "ticker"; result: TickerResult };

/** NAV_GROUPS → 평탄한 라우트 목록 (아이콘 제외 — 팔레트는 텍스트 밀도 우선) */
export function flattenRoutes(groups: typeof NAV_GROUPS): PaletteRoute[] {
  return groups.flatMap((g) => g.items.map((i) => ({ href: i.href, label: i.label, group: g.label })));
}

/** 라벨/경로/그룹 부분 매칭 (대소문자 무시). 빈 쿼리는 전체. */
export function filterRoutes(routes: PaletteRoute[], query: string): PaletteRoute[] {
  const q = query.trim().toLowerCase();
  if (!q) return routes;
  return routes.filter(
    (r) => r.label.toLowerCase().includes(q) || r.href.toLowerCase().includes(q) || r.group.toLowerCase().includes(q),
  );
}

/** KR/US 통화 표기 — explore 검색 드롭다운과 동일 규칙 */
export function formatTickerPrice(ticker: string, price: number | null): string {
  if (price == null) return "";
  const isKr = ticker.endsWith(".KS") || ticker.endsWith(".KQ");
  if (isKr) return `₩${Math.round(price).toLocaleString()}`;
  return `$${price < 100 ? price.toFixed(2) : Math.round(price).toLocaleString()}`;
}

const ALL_ROUTES = flattenRoutes(NAV_GROUPS);

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [tickers, setTickers] = useState<TickerResult[]>([]);
  const [selected, setSelected] = useState(0);
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const routes = useMemo(() => filterRoutes(ALL_ROUTES, query), [query]);
  const items = useMemo<PaletteItem[]>(
    () => [
      ...routes.map((route) => ({ kind: "route" as const, route })),
      ...tickers.map((result) => ({ kind: "ticker" as const, result })),
    ],
    [routes, tickers],
  );

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setTickers([]);
    setSelected(0);
  }, []);

  const navigate = useCallback(
    (item: PaletteItem) => {
      close();
      router.push(item.kind === "route" ? item.route.href : `/ticker/${item.result.ticker}`);
    },
    [close, router],
  );

  // 전역 단축키: Cmd-K / Ctrl-K 토글, Esc 닫기
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      } else if (e.key === "Escape") {
        close();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  // 열리면 입력 포커스
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // 티커 검색 — explore 와 동일한 250ms 디바운스.
  // 동기 setState 는 effect 밖(onQueryChange/close)에서 처리 — react-hooks/set-state-in-effect
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!open || query.trim().length === 0) return;
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await fetch(`/api/tickers/search?q=${encodeURIComponent(query.trim())}`);
        if (res.ok) {
          const data = await res.json();
          setTickers((data.results ?? []).slice(0, 6));
        }
      } catch {
        setTickers([]);
      }
    }, 250);
  }, [open, query]);

  function onQueryChange(value: string) {
    setQuery(value);
    setSelected(0);
    if (value.trim().length === 0) setTickers([]);
  }

  const clamped = Math.min(selected, Math.max(items.length - 1, 0));

  function onInputKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelected((s) => Math.min(s + 1, items.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelected((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter" && items[clamped]) {
      navigate(items[clamped]);
    }
  }

  // 섹션 헤더 위치: 첫 route 항목 앞 / 첫 ticker 항목 앞
  const firstTickerIdx = routes.length;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="ml-auto flex items-center gap-2 rounded-md border border-border bg-muted/40 px-2.5 py-1 text-[11px] text-muted-foreground hover:text-foreground/80 transition-colors"
        data-testid="palette-trigger"
        aria-label={PALETTE.ARIA}
      >
        <Search className="h-3 w-3" />
        {PALETTE.HINT}
        <kbd className="rounded bg-muted px-1 text-[10px]">⌘K</kbd>
      </button>

      {open && (
        <div
          className="fixed inset-0 z-100 flex items-start justify-center bg-black/50 pt-[15vh]"
          data-testid="command-palette-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) close();
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label={PALETTE.ARIA}
            className="w-full max-w-lg rounded-xl border border-border bg-card shadow-2xl overflow-hidden"
            data-testid="command-palette"
          >
            <div className="flex items-center gap-2 border-b border-border px-4">
              <Search className="h-4 w-4 text-zinc-500 shrink-0" />
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => onQueryChange(e.target.value)}
                onKeyDown={onInputKeyDown}
                placeholder={PALETTE.PLACEHOLDER}
                aria-label={PALETTE.PLACEHOLDER}
                className="w-full bg-transparent py-3 text-sm text-foreground placeholder:text-zinc-600 focus:outline-none"
                data-testid="command-palette-input"
              />
            </div>

            <div role="listbox" aria-label={PALETTE.ARIA} className="max-h-80 overflow-y-auto py-1">
              {items.length === 0 && (
                <p className="px-4 py-3 text-xs text-muted-foreground">{PALETTE.NO_RESULTS}</p>
              )}
              {items.map((item, idx) => {
                const isSelected = idx === clamped;
                const header =
                  idx === 0 && routes.length > 0
                    ? PALETTE.SECTION_ROUTES
                    : idx === firstTickerIdx && tickers.length > 0
                      ? PALETTE.SECTION_TICKERS
                      : null;
                return (
                  <div key={item.kind === "route" ? item.route.href : `t-${item.result.ticker}`}>
                    {header && (
                      <p className="px-4 pt-2 pb-1 text-[10px] uppercase tracking-wide text-zinc-600">{header}</p>
                    )}
                    <button
                      type="button"
                      role="option"
                      aria-selected={isSelected}
                      onClick={() => navigate(item)}
                      onMouseEnter={() => setSelected(idx)}
                      className={`flex w-full items-center justify-between px-4 py-2 text-left text-sm transition-colors ${
                        isSelected ? "bg-muted text-foreground" : "text-muted-foreground"
                      }`}
                      data-testid={
                        item.kind === "route"
                          ? `palette-route-${item.route.href}`
                          : `palette-ticker-${item.result.ticker}`
                      }
                    >
                      {item.kind === "route" ? (
                        <>
                          <span>{item.route.label}</span>
                          <span className="text-[10px] text-zinc-600">{item.route.group}</span>
                        </>
                      ) : (
                        <>
                          <span className="flex items-center gap-2 min-w-0">
                            <span className="font-semibold">{item.result.ticker}</span>
                            {item.result.name && (
                              <span className="text-[10px] text-zinc-500 truncate">{item.result.name}</span>
                            )}
                          </span>
                          <span className="text-[10px] text-zinc-400 tabular-nums shrink-0 ml-2">
                            {formatTickerPrice(item.result.ticker, item.result.price)}
                          </span>
                        </>
                      )}
                    </button>
                  </div>
                );
              })}
            </div>

            <div className="border-t border-border px-4 py-1.5">
              <p className="text-[10px] text-zinc-600">{PALETTE.FOOTER}</p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
