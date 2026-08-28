import { describe, it, expect, vi, beforeEach, afterAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { ActionItems } from "@/components/ui/action-items";
import { ACTION } from "@/lib/strings";

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string; [key: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

const urgentItem = {
  ticker: "TSLA",
  action: "SELL",
  confidence: 46,
  agreement: 20,
  pnl_pct: 1.6,
  position_pct: 15.4,
  current_price: 348.95,
  avg_price: 343.39,
  account: "Main",
  stop_loss: 319.35,
  target_1: 412.07,
  target_2: 480.75,
  reasons: ["Certification: 종목 비중 한도 — 위반: TSLA(15.4%>15%)"],
  priority: "urgent",
};

const checkItem = {
  ticker: "NBIS",
  action: "BUY",
  confidence: 59,
  agreement: 40,
  pnl_pct: 32.8,
  position_pct: 7.3,
  current_price: 144.97,
  avg_price: 109.2,
  account: "Main",
  stop_loss: 101.56,
  target_1: 131.04,
  target_2: 152.88,
  reasons: ["1차 익절 도달 (+33%) — 50% 매도 고려", "공매도 19.6% — squeeze 주의"],
  priority: "check",
};

const holdItem = {
  ticker: "GOOGL",
  action: "BUY",
  confidence: 60,
  agreement: 30,
  pnl_pct: 17.5,
  position_pct: 1.9,
  current_price: 317.24,
  avg_price: 269.91,
  account: "Main",
  stop_loss: null,
  target_1: null,
  target_2: null,
  reasons: ["BUY (conf 60)"],
  priority: "hold",
};

// PR A (2026-04-21): portfolio bucket — SIEGE 룰 위반은 "매도" 아닌 "리밸런스 권고".
const portfolioItem = {
  ticker: "BAC",
  action: "HOLD",
  confidence: 62,
  agreement: 90,
  pnl_pct: 5.2,
  position_pct: 19.8,
  current_price: 40.5,
  avg_price: 38.5,
  account: "Main",
  stop_loss: 35.79,
  target_1: 46.2,
  target_2: 53.9,
  reasons: ["리밸런스 권고 — SIEGE: 종목 비중 한도 — 위반: BAC(19.8%>15%)"],
  priority: "portfolio",
};

describe("ActionItems", () => {
  it("renders empty state when no actions", () => {
    render(<ActionItems urgent={[]} check={[]} hold={[]} />);
    expect(screen.getByText("오늘 실행할 액션이 없습니다.")).toBeTruthy();
  });

  it("renders urgent section with red styling", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    expect(screen.getByText("즉시 실행 (1)")).toBeTruthy();
    expect(screen.getByText("TSLA")).toBeTruthy();
    expect(screen.getByText("SELL")).toBeTruthy();
  });

  it("renders check section with amber styling", () => {
    render(<ActionItems urgent={[]} check={[checkItem]} hold={[]} />);
    expect(screen.getByText("오늘 확인 (1)")).toBeTruthy();
    expect(screen.getByText("NBIS")).toBeTruthy();
  });

  it("renders hold section as compact chips", () => {
    render(<ActionItems urgent={[]} check={[]} hold={[holdItem]} />);
    expect(screen.getByText("유지 종목 (1)")).toBeTruthy();
    expect(screen.getByText("GOOGL")).toBeTruthy();
  });

  it("renders all three sections together", () => {
    render(<ActionItems urgent={[urgentItem]} check={[checkItem]} hold={[holdItem]} />);
    expect(screen.getByText("즉시 실행 (1)")).toBeTruthy();
    expect(screen.getByText("오늘 확인 (1)")).toBeTruthy();
    expect(screen.getByText("유지 종목 (1)")).toBeTruthy();
  });

  // PR A (2026-04-21): portfolio bucket regression — SIEGE 룰 위반은 "매도" 아닌
  // "리밸런스 권고". optional prop, back-compat (legacy 3-bucket caller 지원).
  describe("portfolio bucket (PR A)", () => {
    it("renders portfolio section with sky styling", () => {
      render(
        <ActionItems urgent={[]} check={[]} hold={[]} portfolio={[portfolioItem]} />
      );
      expect(screen.getByText(/포트폴리오 리밸런스 \(1\)/)).toBeTruthy();
      expect(screen.getByText("BAC")).toBeTruthy();
      expect(screen.getByText(/리밸런스 권고/)).toBeTruthy();
    });

    it("does not count portfolio items in other buckets", () => {
      render(
        <ActionItems urgent={[]} check={[]} hold={[]} portfolio={[portfolioItem]} />
      );
      expect(screen.queryByText(/즉시 실행/)).toBeNull();
      expect(screen.queryByText(/오늘 확인/)).toBeNull();
      expect(screen.queryByText(/유지 종목/)).toBeNull();
    });

    it("renders all four sections when every bucket is populated", () => {
      render(
        <ActionItems
          urgent={[urgentItem]}
          check={[checkItem]}
          hold={[holdItem]}
          portfolio={[portfolioItem]}
        />
      );
      expect(screen.getByText("즉시 실행 (1)")).toBeTruthy();
      expect(screen.getByText(/포트폴리오 리밸런스 \(1\)/)).toBeTruthy();
      expect(screen.getByText("오늘 확인 (1)")).toBeTruthy();
      expect(screen.getByText("유지 종목 (1)")).toBeTruthy();
    });

    it("back-compat: legacy 3-bucket caller without portfolio prop works", () => {
      // portfolio prop 누락 시 default [] → 렌더링 영향 없음.
      render(<ActionItems urgent={[]} check={[]} hold={[holdItem]} />);
      expect(screen.getByText("유지 종목 (1)")).toBeTruthy();
      expect(screen.queryByText(/포트폴리오 리밸런스/)).toBeNull();
    });

    it("empty state when all four buckets are empty", () => {
      render(<ActionItems urgent={[]} check={[]} hold={[]} portfolio={[]} />);
      expect(screen.getByText("오늘 실행할 액션이 없습니다.")).toBeTruthy();
    });
  });

  it("shows P&L percentage with correct color", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    expect(screen.getByText("+1.6%")).toBeTruthy();
  });

  it("shows action reasons", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    const body = document.body.textContent;
    expect(body).toContain("Certification");
    expect(body).toContain("한도");
  });

  it("shows first reason inline and the rest in quick-peek (#1208)", () => {
    render(<ActionItems urgent={[]} check={[checkItem]} hold={[]} />);
    expect(screen.getByText(/1차 익절/)).toBeTruthy();
    expect(screen.getByText("+1")).toBeTruthy(); // 근거 2건 → +1 표기
    fireEvent.click(screen.getByTestId("action-row"));
    expect(screen.getByText(/공매도/)).toBeTruthy();
  });

  // U2b-2 (#1208): 확장은 버튼이 아니라 행 클릭(quick-peek)
  it("expands quick-peek on row click", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    fireEvent.click(screen.getByTestId("action-row"));
    expect(screen.getByText("현재가")).toBeTruthy();
    expect(screen.getByText("손절")).toBeTruthy();
    expect(screen.getByTestId("action-row-peek")).toBeTruthy();
  });

  // #1251 (was #1208 codex P1): 키보드 접근의 **주체가 행에서 버튼으로** 옮겨졌다.
  //
  // #1208 은 `<tr>` 에 tabIndex/onKeyDown/aria-expanded 를 달아 키보드를 열었다. 동작은
  // 했지만 `<tr>` 의 암묵 role 은 `row` 라 스크린리더가 disclosure 로 읽지 못했고, 행마다
  // 쓸모없는 탭 스톱이 하나씩 생겼다. 이제 네이티브 `<button>` 이 컨트롤이다 —
  // Enter/Space 활성화·role·포커스를 **플랫폼이** 준다.
  //
  // ⚠️ 이 잠금이 `fireEvent.keyDown(button, {key:"Enter"})` 이 아닌 이유: jsdom 은 네이티브
  // 버튼의 키 입력을 click 으로 합성하지 않는다(그건 브라우저 동작이고 user-event 가 흉내낸다.
  // 이 레포엔 user-event 가 없다). keyDown 을 쏘면 **버튼이 아니어도 통과**하는 가짜 잠금이
  // 되므로, 활성화 대신 **그 활성화를 보장하는 성질**(네이티브 button 인가)을 직접 잰다.
  it("quick-peek toggle is a native button — keyboard activation comes from the platform", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    const toggle = screen.getByTestId("action-row-toggle");
    expect(toggle.tagName).toBe("BUTTON");
    expect(toggle.getAttribute("type")).toBe("button"); // submit 이면 폼 안에서 오작동
    fireEvent.click(toggle);
    expect(screen.getByTestId("action-row-peek")).toBeTruthy();
    fireEvent.click(toggle);
    expect(screen.queryByTestId("action-row-peek")).toBeNull();
  });

  it("toggle announces disclosure state and points at the panel it controls", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    const toggle = screen.getByTestId("action-row-toggle");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    // 접근명에 종목이 들어가야 행이 여럿일 때 "상세 펼치기" 가 구분된다.
    expect(toggle.getAttribute("aria-label")).toContain(urgentItem.ticker);

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const controls = toggle.getAttribute("aria-controls");
    expect(controls).toBeTruthy();
    // 관계가 **실제로** 이어져야 한다 — 속성만 있고 대상이 없으면 SR 에겐 없는 것과 같다.
    expect(screen.getByTestId("action-row-peek").getAttribute("id")).toBe(controls);
  });

  it("row is no longer a phantom tab stop or a fake disclosure", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    const row = screen.getByTestId("action-row");
    expect(row.getAttribute("tabindex")).toBeNull();
    expect(row.getAttribute("aria-expanded")).toBeNull();
    // 마우스 편의는 유지 — 행 아무 데나 눌러도 펼쳐진다.
    fireEvent.click(row);
    expect(screen.getByTestId("action-row-peek")).toBeTruthy();
  });

  // #1279: 시세 없는 보유(비상장)는 손익이 null 이다.
  it("null pnl renders 미상, not a fabricated 0%", () => {
    const unpriced = { ...urgentItem, ticker: "PRIVATECO", pnl_pct: null, current_price: null };
    render(<ActionItems urgent={[unpriced]} check={[]} hold={[]} />);
    expect(screen.getByText(ACTION.PNL_UNKNOWN)).toBeTruthy();
    // 이전 코드는 `null >= 0` 이 true 라 "+0.0%" 를 초록으로 찍었다 — 보합으로 읽힌다.
    expect(screen.queryByText("+0.0%")).toBeNull();
    expect(screen.queryByText("0.0%")).toBeNull();
  });

  it("numeric pnl still renders with sign and one decimal", () => {
    render(<ActionItems urgent={[{ ...urgentItem, pnl_pct: -3.14 }]} check={[]} hold={[]} />);
    expect(screen.getByText("-3.1%")).toBeTruthy();
    expect(screen.queryByText(ACTION.PNL_UNKNOWN)).toBeNull();
  });

  it("each row gets its own aria-controls target", () => {
    render(<ActionItems urgent={[urgentItem]} check={[checkItem]} hold={[]} />);
    const ids = screen.getAllByTestId("action-row-toggle").map((b) => b.getAttribute("aria-controls"));
    expect(ids).toHaveLength(2);
    expect(new Set(ids).size).toBe(2); // 공유하면 SR 이 엉뚱한 패널을 가리킨다
  });

  it("collapses quick-peek on second row click", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    const row = screen.getByTestId("action-row");
    fireEvent.click(row);
    expect(screen.getByText("현재가")).toBeTruthy();
    fireEvent.click(row);
    expect(screen.queryByText("현재가")).toBeNull();
  });

  it("formats KR prices with won symbol", () => {
    const krItem = { ...urgentItem, ticker: "005930.KS", current_price: 200750, stop_loss: 180675, target_1: 230862 };
    render(<ActionItems urgent={[krItem]} check={[]} hold={[]} />);
    fireEvent.click(screen.getByTestId("action-row"));
    const body = document.body.textContent;
    expect(body).toContain("₩");
  });

  it("links ticker to detail page", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    const link = screen.getByText("TSLA").closest("a");
    expect(link?.getAttribute("href")).toBe("/ticker/TSLA");
  });

  it("shows account label", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    expect(screen.getByText("Main")).toBeTruthy();
  });

  it("shows confidence and weight in row cells (#1208 table)", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    expect(screen.getByText("46")).toBeTruthy();
    expect(screen.getByText("15.4%")).toBeTruthy();
  });

  it("hold chips link to ticker page", () => {
    render(<ActionItems urgent={[]} check={[]} hold={[holdItem]} />);
    const link = screen.getByText("GOOGL").closest("a");
    expect(link?.getAttribute("href")).toBe("/ticker/GOOGL");
  });

  it("hold chips show action and confidence", () => {
    render(<ActionItems urgent={[]} check={[]} hold={[holdItem]} />);
    expect(screen.getByText("BUY 60")).toBeTruthy();
  });

  it("handles negative P&L", () => {
    const lossItem = { ...checkItem, pnl_pct: -5.3 };
    render(<ActionItems urgent={[]} check={[lossItem]} hold={[]} />);
    expect(screen.getByText("-5.3%")).toBeTruthy();
  });

  it("shows Korean name with ticker in title attr (#1208 dense row)", () => {
    const krItem = { ...urgentItem, ticker: "005930.KS", name: "삼성전자" };
    render(<ActionItems urgent={[krItem]} check={[]} hold={[]} />);
    const link = screen.getByText("삼성전자");
    expect(link.getAttribute("title")).toContain("005930.KS");
  });

  it("shows ticker when name is null", () => {
    const noName = { ...urgentItem, name: null };
    render(<ActionItems urgent={[noName]} check={[]} hold={[]} />);
    expect(screen.getByText("TSLA")).toBeTruthy();
  });

  it("hides account when empty", () => {
    const noAccount = { ...urgentItem, account: "" };
    render(<ActionItems urgent={[noAccount]} check={[]} hold={[]} />);
    // Should not render empty account span
    const body = document.body.textContent ?? "";
    expect(body).not.toContain("Main");
  });

  it("shows HOLD action in hold chip", () => {
    const holdAction = { ...holdItem, action: "HOLD", reasons: ["HOLD (conf 52)"] };
    render(<ActionItems urgent={[]} check={[]} hold={[holdAction]} />);
    expect(screen.getByText("HOLD 60")).toBeTruthy();
  });

  it("shows name in hold chips for KR tickers", () => {
    const krHold = { ...holdItem, ticker: "000660.KS", name: "SK하이닉스" };
    render(<ActionItems urgent={[]} check={[]} hold={[krHold]} />);
    expect(screen.getByText("SK하이닉스")).toBeTruthy();
  });

  it("formats null prices as dash in expanded detail", () => {
    const nullPrices = { ...urgentItem, stop_loss: null, target_1: null };
    render(<ActionItems urgent={[nullPrices]} check={[]} hold={[]} />);
    fireEvent.click(screen.getByTestId("action-row"));
    const body = document.body.textContent ?? "";
    expect(body).toContain("—");
  });

  // #1182: 증거 체인 링크 — decision_id 있으면 /decisions/[id] 로, 없으면 링크 생략
  it("renders evidence-chain link when decision_id is present", () => {
    const withDecision = { ...urgentItem, decision_id: 42, as_of: "2026-08-25" };
    render(<ActionItems urgent={[withDecision]} check={[]} hold={[]} />);
    const link = screen.getByText(/증거 체인/).closest("a");
    expect(link?.getAttribute("href")).toBe("/decisions/42");
    // as_of 는 quick-peek 로 이동 (#1208)
    fireEvent.click(screen.getByTestId("action-row"));
    expect(document.body.textContent).toContain("2026-08-25");
  });

  it("omits evidence-chain link when decision_id is null", () => {
    const noDecision = { ...urgentItem, decision_id: null, as_of: "2026-08-25" };
    render(<ActionItems urgent={[noDecision]} check={[]} hold={[]} />);
    expect(screen.queryByText(/증거 체인/)).toBeNull();
  });
});

// #1212 U2b-4: NEW 배지 + 확인(ack) — per-viewer seen-state.
// ⚠️ 스토리지는 환경 의존이다: 로컬 Node 26 jsdom 엔 window.localStorage 가
// 아예 없고(실험적 webstorage 게터가 undefined), CI Node 22 jsdom 은 실동작
// 스토리지를 제공한다. 후자에서 ack 이 파일 내 다음 테스트로 지속돼 CI 만
// 깨졌다 (run 32814106230, expected 2 → got 1). 인메모리 스텁 + 매 테스트
// 초기화로 양쪽 환경을 동일·결정론적으로 만든다.
describe("NEW badge + ack (#1212)", () => {
  const asOfItem = { ...urgentItem, as_of: "2026-08-25", decision_id: 7 };

  let ackStore: Record<string, string> = {};
  const storageStub = {
    getItem: (k: string) => (k in ackStore ? ackStore[k] : null),
    setItem: (k: string, v: string) => { ackStore[k] = String(v); },
    removeItem: (k: string) => { delete ackStore[k]; },
    clear: () => { ackStore = {}; },
    key: (i: number) => Object.keys(ackStore)[i] ?? null,
    get length() { return Object.keys(ackStore).length; },
  } as Storage;
  const originalDescriptor = Object.getOwnPropertyDescriptor(window, "localStorage");
  beforeEach(() => {
    ackStore = {};
    Object.defineProperty(window, "localStorage", { value: storageStub, configurable: true });
  });
  afterAll(() => {
    if (originalDescriptor) Object.defineProperty(window, "localStorage", originalDescriptor);
    else delete (window as { localStorage?: Storage }).localStorage;
  });

  it("marks un-acked rows NEW after mount", () => {
    render(<ActionItems urgent={[asOfItem]} check={[checkItem]} hold={[]} />);
    expect(screen.getAllByTestId("action-new-badge")).toHaveLength(2);
  });

  it("확인 in the quick-peek clears the NEW badge for that row only", () => {
    render(<ActionItems urgent={[asOfItem]} check={[checkItem]} hold={[]} />);
    const rows = screen.getAllByTestId("action-row");
    fireEvent.click(rows[0]); // expand urgent row
    fireEvent.click(screen.getByTestId("action-ack-button"));
    expect(screen.getAllByTestId("action-new-badge")).toHaveLength(1); // check 행만 남음
  });

  it("hold chips never carry NEW badges", () => {
    render(<ActionItems urgent={[]} check={[]} hold={[holdItem]} />);
    expect(screen.queryByTestId("action-new-badge")).not.toBeInTheDocument();
  });

  // codex R1 P1 잠금: 같은 ticker|account|action 튜플이 두 버킷에 동시에 떠도
  // ack identity 가 버킷(priority)까지 포함하므로 한쪽 확인이 다른쪽 NEW 를
  // 지우지 않는다.
  it("acking a row in one bucket keeps the same tuple NEW in another bucket", () => {
    const inUrgent = { ...asOfItem, priority: "urgent" };
    const inPortfolio = { ...asOfItem, priority: "portfolio" };
    render(<ActionItems urgent={[inUrgent]} check={[]} hold={[]} portfolio={[inPortfolio]} />);
    expect(screen.getAllByTestId("action-new-badge")).toHaveLength(2);
    fireEvent.click(screen.getAllByTestId("action-row")[0]); // urgent 행 확장
    fireEvent.click(screen.getByTestId("action-ack-button"));
    expect(screen.getAllByTestId("action-new-badge")).toHaveLength(1);
  });

  // codex R1 P3 잠금: 서버 렌더(HTML 문자열)에는 NEW 배지가 없어야 한다 —
  // hydration 게이트(useSyncExternalStore 서버 스냅샷 false)가 렌더 시점
  // loadAckMap() 직독(서버·클라 마크업 불일치)으로 회귀하면 여기서 잡힌다.
  // (effect 내 동기 setState 회귀는 lint 가 잡는다 — 이 잠금과 역할 분담.)
  it("server render carries no NEW badge (hydration gate lock)", () => {
    const html = renderToString(<ActionItems urgent={[asOfItem]} check={[checkItem]} hold={[]} />);
    expect(html).not.toContain("action-new-badge");
  });
});
