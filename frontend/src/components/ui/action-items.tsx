"use client";

import Link from "next/link";
import { useId, useMemo, useState, useSyncExternalStore, Fragment } from "react";
import { ACTION } from "@/lib/strings";
import { formatMoney } from "@/lib/format";
import { type AckMap, ackItem, actionKey, isNewItem, loadAckMap } from "@/lib/action-ack";

export interface ActionItem {
  ticker: string;
  name?: string | null;
  action: string;
  confidence: number;
  agreement?: number | null;
  /** 시세 미수집이면 `null` — 측정 불가이지 0% 가 아니다 (#1279). */
  pnl_pct: number | null;
  /**
   * 환율 미수집이면 `null` — 비중의 분모(통화 혼합 총액)를 모른다 (#1284).
   * 바로 위 `pnl_pct` 와 **같은 계약**이다: 측정 불가는 0 이 아니다.
   */
  position_pct: number | null;
  current_price?: number | null;
  avg_price?: number | null;
  account?: string;
  stop_loss?: number | null;
  target_1?: number | null;
  target_2?: number | null;
  reasons: string[];
  priority: string;
  // #1182: 증거 체인 (/decisions/[id]) + 판정 기준일 — 매칭 decision 없으면 null
  decision_id?: number | null;
  as_of?: string | null;
}

interface ActionItemsProps {
  urgent: ActionItem[];
  check: ActionItem[];
  hold: ActionItem[];
  // PR A (2026-04-21): portfolio bucket — SIEGE 룰 위반은 "매도 강제" 가 아닌
  // "리밸런스 권고". optional 로 선언해 legacy 호출자 back-compat.
  portfolio?: ActionItem[];
}

// #1212 hydration 게이트용 안정 참조 (useSyncExternalStore 인자)
const emptySubscribe = () => () => {};
const getTrue = () => true;
const getFalse = () => false;

// U2b-2 (#1208): 카드 → 32px 밀집 테이블 행. 버킷(심각도) 구조는 유지 —
// urgent > portfolio > check 순서가 곧 예외 큐 정렬이다 (plan §4.5).
const bucketStyles = {
  urgent: { dot: "bg-red-500", title: "text-red-400", accent: "border-l-red-500/60" },
  portfolio: { dot: "bg-sky-500", title: "text-sky-400", accent: "border-l-sky-500/60" },
  check: { dot: "bg-amber-500", title: "text-amber-400", accent: "border-l-amber-500/60" },
};

function actionTagCls(action: string): string {
  if (action === "SELL") return "bg-red-500/20 text-red-400";
  if (action === "BUY") return "bg-emerald-500/20 text-emerald-400";
  return "bg-zinc-700 text-zinc-400";
}

interface AckProps {
  /** null = 마운트 전(미로드) — NEW 미표시로 hydration 안전 (#1212) */
  ackMap: AckMap | null;
  onAck: (item: ActionItem) => void;
}

function ActionRow({ item, accent, ackMap, onAck }: { item: ActionItem; accent: string } & AckProps) {
  const [expanded, setExpanded] = useState(false);
  // #1251: 확장 패널과 컨트롤을 aria-controls 로 잇는다. `useId` 는 SSR/CSR 간
  // 안정적이라 hydration 경고가 없다 (actionKey 로 만들면 티커에 공백·특수문자가 섞여
  // 유효하지 않은 id 가 될 수 있다).
  const peekId = useId();
  const fmt = (v: number | null | undefined) => formatMoney(v, { ticker: item.ticker });
  const confPct = Math.max(0, Math.min(100, item.confidence));
  const isNew = isNewItem(item, ackMap);

  return (
    <Fragment>
      <tr
        className={`border-b border-zinc-800/40 border-l-2 ${accent} hover:bg-zinc-800/30 cursor-pointer transition-colors focus-visible:outline-2 focus-visible:outline-blue-400/75`}
        // 마우스 편의: 행 아무 데나 눌러도 펼쳐진다. **시맨틱은 아래 버튼이 갖는다** —
        // #1208 은 이 행에 tabIndex/onKeyDown/aria-expanded 를 달아 키보드를 열었지만,
        // `<tr>` 의 암묵 role 은 `row` 라 스크린리더가 disclosure 로 읽지 못하고
        // 행마다 쓸모없는 탭 스톱만 하나씩 생겼다 (#1251). 네이티브 `<button>` 은
        // Enter/Space 활성화·role·포커스를 플랫폼에서 받는다.
        onClick={() => setExpanded(!expanded)}
        data-testid="action-row"
      >
        <td className="h-8 px-2 whitespace-nowrap">
          <button
            type="button"
            data-testid="action-row-toggle"
            aria-expanded={expanded}
            aria-controls={peekId}
            aria-label={`${item.name || item.ticker} ${expanded ? ACTION.PEEK_COLLAPSE : ACTION.PEEK_EXPAND}`}
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
            className="mr-1 align-middle inline-flex items-center justify-center w-4 h-4 -my-1 rounded text-zinc-500 hover:text-zinc-200 transition-colors focus-visible:outline-2 focus-visible:outline-blue-400/75"
          >
            <span aria-hidden="true" className={`text-[9px] leading-none transition-transform ${expanded ? "rotate-90" : ""}`}>&#9654;</span>
          </button>
          <Link
            href={`/ticker/${item.ticker}`}
            className="text-xs font-semibold text-zinc-100 hover:text-white transition-colors"
            onClick={(e) => e.stopPropagation()}
            title={item.name ? `${item.name} (${item.ticker})` : item.ticker}
          >
            {item.name || item.ticker}
          </Link>
          {/* #1212: 미확인 배지 — 판정일(as_of) 갱신 시 재표시 (re-alert) */}
          {isNew && (
            <span
              data-testid="action-new-badge"
              title={item.as_of ? `판정 ${item.as_of}` : undefined}
              className="ml-1.5 align-middle text-[9px] font-bold px-1 py-px rounded bg-blue-500/20 text-blue-400"
            >
              {ACTION.NEW}
            </span>
          )}
        </td>
        <td className="h-8 px-2 whitespace-nowrap hidden md:table-cell text-[11px] text-zinc-400">{item.account ?? "—"}</td>
        <td className="h-8 px-2 whitespace-nowrap">
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${actionTagCls(item.action)}`}>{item.action}</span>
        </td>
        <td className="h-8 px-2 w-full max-w-0">
          <p className="text-xs text-zinc-400 truncate" title={item.reasons.join(" · ")}>
            {item.reasons[0] ?? "—"}
            {item.reasons.length > 1 && <span className="text-zinc-600"> +{item.reasons.length - 1}</span>}
          </p>
        </td>
        {/* #1279: `null` 은 미상이다. 이전 코드는 `null >= 0` 이 true 라 **초록 +** 가
            붙고 `null.toFixed` 로 터졌다 — JS 의 null 강제변환이 만든 두 겹 오류. */}
        <td className={`h-8 px-2 whitespace-nowrap text-right text-xs font-semibold tabular-nums ${
          item.pnl_pct == null ? "text-zinc-500" : item.pnl_pct >= 0 ? "text-emerald-400" : "text-red-400"
        }`}>
          {item.pnl_pct == null
            ? ACTION.PNL_UNKNOWN
            : `${item.pnl_pct >= 0 ? "+" : ""}${item.pnl_pct.toFixed(1)}%`}
        </td>
        <td className="h-8 px-2 whitespace-nowrap hidden md:table-cell text-right text-[11px] text-zinc-400 tabular-nums">
          {item.position_pct == null ? ACTION.PNL_UNKNOWN : `${item.position_pct.toFixed(1)}%`}
        </td>
        <td className="h-8 px-2 whitespace-nowrap">
          <span className="inline-flex items-center gap-1.5">
            <span className="relative inline-block w-12 h-1 rounded-full bg-zinc-800 overflow-hidden align-middle">
              <span className="absolute inset-y-0 left-0 rounded-full bg-zinc-500" style={{ width: `${confPct}%` }} />
            </span>
            <span className="text-[11px] text-zinc-400 tabular-nums">{item.confidence}</span>
          </span>
        </td>
        <td className="h-8 px-2 whitespace-nowrap text-right">
          {item.decision_id != null ? (
            <Link
              href={`/decisions/${item.decision_id}`}
              // design-review F-007: 13px 텍스트 링크의 히트 영역을 패딩+네거티브 마진으로
              // 확장 (레이아웃 불변) — 이 링크가 추적성 심장(/decisions/[id])의 진입점이다
              className="inline-block p-1.5 -m-1.5 text-[11px] text-zinc-500 hover:text-zinc-300 transition-colors focus-visible:outline-2 focus-visible:outline-blue-400/75"
              onClick={(e) => e.stopPropagation()}
            >
              {ACTION.EVIDENCE} →
            </Link>
          ) : (
            <span className="text-[11px] text-zinc-700">—</span>
          )}
        </td>
      </tr>
      {/* quick-peek (#1208, codex 2R 합의): 라우트 이동 없이 가격 레벨·전체 근거 확인 */}
      {expanded && (
        <tr id={peekId} className="border-b border-zinc-800/40 bg-zinc-900/40" data-testid="action-row-peek">
          <td colSpan={8} className="px-3 py-2">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
              {/* <md 에서 행이 숨기는 계좌·비중을 peek 가 복원 (#1208 codex P2) */}
              {item.account && <span className="md:hidden"><span className="text-zinc-600">계좌</span> <span className="text-zinc-300">{item.account}</span></span>}
              <span className="md:hidden"><span className="text-zinc-600">비중</span> <span className="text-zinc-300 tabular-nums">{item.position_pct == null ? ACTION.PNL_UNKNOWN : `${item.position_pct.toFixed(1)}%`}</span></span>
              <span><span className="text-zinc-600">현재가</span> <span className="text-zinc-300 tabular-nums">{fmt(item.current_price)}</span></span>
              <span><span className="text-zinc-600">손절</span> <span className="text-red-400 tabular-nums">{fmt(item.stop_loss)}</span></span>
              <span><span className="text-zinc-600">1차익절</span> <span className="text-emerald-400 tabular-nums">{fmt(item.target_1)}</span></span>
              {item.target_2 != null && (
                <span><span className="text-zinc-600">2차익절</span> <span className="text-emerald-400 tabular-nums">{fmt(item.target_2)}</span></span>
              )}
              {item.as_of && <span className="text-zinc-600">판정 {item.as_of}</span>}
              {/* #1212: ack — NEW 해제 (localStorage, per-viewer) */}
              {isNew && (
                <button
                  type="button"
                  data-testid="action-ack-button"
                  className="ml-auto text-[11px] px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 hover:bg-zinc-700 hover:text-zinc-100 transition-colors"
                  onClick={(e) => {
                    e.stopPropagation();
                    onAck(item);
                  }}
                >
                  {ACTION.ACK}
                </button>
              )}
            </div>
            {item.reasons.length > 1 && (
              <div className="mt-1 space-y-0.5">
                {item.reasons.slice(1).map((r, i) => (
                  <p key={i} className="text-[11px] text-zinc-500 leading-tight">{r}</p>
                ))}
              </div>
            )}
          </td>
        </tr>
      )}
    </Fragment>
  );
}

function ActionBucketTable({ items, kind, title, ackMap, onAck }: { items: ActionItem[]; kind: keyof typeof bucketStyles; title: string } & AckProps) {
  const style = bucketStyles[kind];
  if (items.length === 0) return null;
  return (
    <div>
      <h3 className={`text-xs font-semibold ${style.title} mb-1 flex items-center gap-1.5`}>
        <span className={`w-2 h-2 rounded-full ${style.dot}`} />
        {title} ({items.length})
      </h3>
      <div className="overflow-x-auto rounded border border-zinc-800/60 bg-zinc-900/30">
        <table className="w-full text-left">
          {/* design-review F-001: 수익률/비중/확신도 숫자가 무라벨이었다 — 초경량 헤더로 명명.
              th 반응형 클래스는 아래 td 와 1:1 (계좌·비중 = hidden md:table-cell) */}
          <thead>
            <tr className="border-b border-zinc-800/40">
              <th scope="col" className="px-2 py-1 text-[9px] font-medium text-zinc-600">{ACTION.COL_TICKER}</th>
              <th scope="col" className="px-2 py-1 text-[9px] font-medium text-zinc-600 hidden md:table-cell">{ACTION.COL_ACCOUNT}</th>
              <th scope="col" className="px-2 py-1 text-[9px] font-medium text-zinc-600">{ACTION.COL_ACTION}</th>
              <th scope="col" className="px-2 py-1 text-[9px] font-medium text-zinc-600">{ACTION.COL_REASON}</th>
              <th scope="col" className="px-2 py-1 text-[9px] font-medium text-zinc-600 text-right">{ACTION.COL_PNL}</th>
              <th scope="col" className="px-2 py-1 text-[9px] font-medium text-zinc-600 text-right hidden md:table-cell">{ACTION.COL_WEIGHT}</th>
              <th scope="col" className="px-2 py-1 text-[9px] font-medium text-zinc-600">{ACTION.COL_CONF}</th>
              {/* 증거 체인 컬럼 — 링크 텍스트가 자기 서술적이라 헤더 라벨 생략 (getByText 충돌 회피) */}
              <th scope="col" className="px-2 py-1" />

            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              // key = seen-state identity (codex R1 P2): action/priority 가 바뀐 행이
              // 같은 ActionRow 인스턴스(expanded 등 로컬 상태)를 물려받지 않게 한다
              <ActionRow key={actionKey(item)} item={item} accent={style.accent} ackMap={ackMap} onAck={onAck} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ActionItems({ urgent, check, hold, portfolio = [] }: ActionItemsProps) {
  const total = urgent.length + check.length + hold.length + portfolio.length;

  // #1212: seen-state 는 hydration 후에만 읽는다 — SSR 마크업과 첫 클라 렌더가
  // 일치해야 하므로 useSyncExternalStore 게이트(서버 false → 클라 true)를 쓴다.
  // (effect 내 동기 setState 는 lint 금지 — cascading render.) hold 칩은 배지
  // 없음 (노이즈 — 버킷 3종만).
  const hydrated = useSyncExternalStore(emptySubscribe, getTrue, getFalse);
  const loadedMap = useMemo(() => (hydrated ? loadAckMap() : null), [hydrated]);
  const [ackOverride, setAckOverride] = useState<AckMap | null>(null);
  const ackMap = ackOverride ?? loadedMap;
  const onAck = (item: ActionItem) => {
    // `?? {}` 는 구조적 도달 불가 (#1214): 확인 버튼은 isNew 일 때만 렌더되고
    // isNewItem 은 ackMap===null(hydration 전)이면 항상 false — 클릭 시점의
    // ackMap 은 항상 객체다. 미래 리팩터 대비 방어로만 남긴다.
    /* v8 ignore next */
    setAckOverride(ackItem(ackMap ?? {}, item));
  };

  if (total === 0) {
    return (
      <div className="rounded-lg bg-zinc-900/40 border border-zinc-800/60 p-4 text-center text-sm text-zinc-500">
        {ACTION.EMPTY}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* 🔴 즉시 실행 */}
      <ActionBucketTable items={urgent} kind="urgent" title={ACTION.URGENT} ackMap={ackMap} onAck={onAck} />

      {/* 📊 포트폴리오 리밸런스 — PR A: SIEGE 룰 위반을 "매도" 로 surface 하지 않기 */}
      <ActionBucketTable items={portfolio} kind="portfolio" title={ACTION.PORTFOLIO} ackMap={ackMap} onAck={onAck} />

      {/* 🟡 오늘 확인 */}
      <ActionBucketTable items={check} kind="check" title={ACTION.CHECK} ackMap={ackMap} onAck={onAck} />

      {/* ✅ 유지 — 칩 유지 (행 승격은 노이즈, 목업 합의) */}
      {hold.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-zinc-500 mb-1.5 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-zinc-500" />
            {ACTION.HOLD_SUMMARY} ({hold.length})
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {hold.map((item) => (
              <Link
                key={actionKey(item)}
                href={`/ticker/${item.ticker}`}
                className="inline-flex items-center gap-1 px-2 py-1 rounded bg-zinc-900/60 border border-zinc-800/40 text-[10px] hover:bg-zinc-800/60 transition-colors"
              >
                <span className="text-zinc-300">{item.name || item.ticker}</span>
                <span className={`tabular-nums font-medium ${item.action === "BUY" ? "text-emerald-500" : "text-zinc-500"}`}>
                  {item.action} {item.confidence}
                </span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
