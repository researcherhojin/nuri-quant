/**
 * CommandPalette (#1226 U5b) — 단축키 토글 · 라우트 필터 · 티커 검색 · 키보드 내비.
 */
import { render, screen, fireEvent, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PALETTE } from "@/lib/strings";
import { NAV_GROUPS } from "@/components/ui/sidebar";
import {
  CommandPalette,
  filterRoutes,
  flattenRoutes,
  formatTickerPrice,
} from "@/components/ui/command-palette";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: (...args: unknown[]) => pushMock(...args) }),
  usePathname: () => "/",
}));

const ROUTES = flattenRoutes(NAV_GROUPS);

describe("pure helpers", () => {
  it("flattenRoutes: 사이드바 전 라우트를 그룹 라벨과 함께 평탄화", () => {
    const hrefs = ROUTES.map((r) => r.href);
    expect(hrefs).toContain("/");
    expect(hrefs).toContain("/decisions");
    expect(hrefs).toContain("/evidence");
    const decisions = ROUTES.find((r) => r.href === "/decisions");
    expect(decisions?.group.length).toBeGreaterThan(0);
  });

  it("filterRoutes: 빈 쿼리는 전체, 라벨/그룹 부분 매칭은 대소문자 무시", () => {
    expect(filterRoutes(ROUTES, "")).toHaveLength(ROUTES.length);
    const byLabel = filterRoutes(ROUTES, "deci");
    expect(byLabel.map((r) => r.href)).toContain("/decisions");
    const byGroup = filterRoutes(ROUTES, ROUTES[0].group);
    expect(byGroup.length).toBeGreaterThan(0);
    expect(filterRoutes(ROUTES, "zzz-none")).toHaveLength(0);
  });

  it("formatTickerPrice: KR=₩ 정수, US<100=소수 2자리, US≥100=정수, null=빈 문자열", () => {
    expect(formatTickerPrice("005930.KS", 71234.5)).toBe("₩71,235");
    expect(formatTickerPrice("IONQ", 42.126)).toBe("$42.13");
    expect(formatTickerPrice("NVDA", 1234.6)).toBe("$1,235");
    expect(formatTickerPrice("NVDA", null)).toBe("");
  });
});

describe("CommandPalette", () => {
  beforeEach(() => {
    pushMock.mockClear();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ results: [{ ticker: "AAA", name: "테스트", price: 12.3, date: "2026-08-25" }] }),
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("트리거 버튼 클릭 → 다이얼로그 열림, 전 라우트 표시", () => {
    render(<CommandPalette />);
    expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("palette-trigger"));
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
    expect(screen.getByTestId("palette-route-/decisions")).toBeInTheDocument();
    expect(screen.getByText(PALETTE.SECTION_ROUTES)).toBeInTheDocument();
  });

  it("Cmd-K 토글 · Escape 닫기", () => {
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument();
    // Ctrl-K (비 macOS)
    fireEvent.keyDown(window, { key: "K", ctrlKey: true });
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
  });

  it("쿼리로 라우트 필터 + Enter 로 이동 후 닫힘", () => {
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const input = screen.getByTestId("command-palette-input");
    fireEvent.change(input, { target: { value: "deci" } });
    expect(screen.getByTestId("palette-route-/decisions")).toBeInTheDocument();
    expect(screen.queryByTestId("palette-route-/pipeline")).not.toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(pushMock).toHaveBeenCalledWith("/decisions");
    expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument();
  });

  it("ArrowDown/ArrowUp 내비 — Up 은 0 에서 클램프", () => {
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const input = screen.getByTestId("command-palette-input");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(pushMock).toHaveBeenCalledWith(ROUTES[1].href);
    // 재오픈 후 Up 연타 → 0 클램프 (첫 항목 유지)
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const input2 = screen.getByTestId("command-palette-input");
    fireEvent.keyDown(input2, { key: "ArrowUp" });
    fireEvent.keyDown(input2, { key: "Enter" });
    expect(pushMock).toHaveBeenLastCalledWith(ROUTES[0].href);
  });

  it("mouseEnter 로 선택 이동", () => {
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const second = screen.getByTestId(`palette-route-${ROUTES[1].href}`);
    fireEvent.mouseEnter(second);
    expect(second).toHaveAttribute("aria-selected", "true");
  });

  it("티커 검색: 250ms 디바운스 후 결과 렌더, 클릭 → /ticker/[symbol]", async () => {
    vi.useFakeTimers();
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const input = screen.getByTestId("command-palette-input");
    fireEvent.change(input, { target: { value: "AAA" } });
    await act(async () => {
      vi.advanceTimersByTime(260);
    });
    expect(fetch).toHaveBeenCalledWith("/api/tickers/search?q=AAA");
    expect(screen.getByTestId("palette-ticker-AAA")).toBeInTheDocument();
    expect(screen.getByText(PALETTE.SECTION_TICKERS)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("palette-ticker-AAA"));
    expect(pushMock).toHaveBeenCalledWith("/ticker/AAA");
  });

  it("입력을 비우면 티커 결과 즉시 초기화", async () => {
    vi.useFakeTimers();
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const input = screen.getByTestId("command-palette-input");
    fireEvent.change(input, { target: { value: "AAA" } });
    await act(async () => {
      vi.advanceTimersByTime(260);
    });
    expect(screen.getByTestId("palette-ticker-AAA")).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "" } });
    expect(screen.queryByTestId("palette-ticker-AAA")).not.toBeInTheDocument();
  });

  it("검색 실패는 조용히 빈 결과 (fetch reject)", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    fireEvent.change(screen.getByTestId("command-palette-input"), { target: { value: "AAA" } });
    await act(async () => {
      vi.advanceTimersByTime(260);
    });
    expect(screen.queryByTestId("palette-ticker-AAA")).not.toBeInTheDocument();
    // 라우트 매칭도 없으면 결과 없음 문구
    fireEvent.change(screen.getByTestId("command-palette-input"), { target: { value: "zzz-none" } });
    await act(async () => {
      vi.advanceTimersByTime(260);
    });
    expect(screen.getByText(PALETTE.NO_RESULTS)).toBeInTheDocument();
  });

  it("res.ok=false 와 results 필드 부재는 빈 결과로 강등", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: () => Promise.resolve({}) }));
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    fireEvent.change(screen.getByTestId("command-palette-input"), { target: { value: "AAA" } });
    await act(async () => {
      vi.advanceTimersByTime(260);
    });
    expect(screen.queryByTestId("palette-ticker-AAA")).not.toBeInTheDocument();

    // results 키 없는 200 응답 → `?? []` 분기
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) }));
    fireEvent.change(screen.getByTestId("command-palette-input"), { target: { value: "BBB" } });
    await act(async () => {
      vi.advanceTimersByTime(260);
    });
    expect(screen.queryByTestId("palette-ticker-BBB")).not.toBeInTheDocument();
  });

  it("결과 0건에서 Enter 는 아무것도 하지 않는다", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ results: [] }) }));
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const input = screen.getByTestId("command-palette-input");
    fireEvent.change(input, { target: { value: "zzz-none" } });
    await act(async () => {
      vi.advanceTimersByTime(260);
    });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(pushMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
  });

  it("백드롭 클릭 → 닫힘 (패널 내부 클릭은 유지)", () => {
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    fireEvent.mouseDown(screen.getByTestId("command-palette"));
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId("command-palette-backdrop"));
    expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument();
  });

  it("낡은 응답 폐기: A 요청이 B 요청보다 늦게 도착해도 B 결과 유지 (codex P1)", async () => {
    vi.useFakeTimers();
    let resolveA: ((v: unknown) => void) | undefined;
    let resolveB: ((v: unknown) => void) | undefined;
    const mk = (t: string) => ({ ok: true, json: () => Promise.resolve({ results: [{ ticker: t, name: null, price: 1 }] }) });
    vi.stubGlobal(
      "fetch",
      vi.fn()
        .mockImplementationOnce(() => new Promise((r) => { resolveA = r; }))
        .mockImplementationOnce(() => new Promise((r) => { resolveB = r; })),
    );
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const input = screen.getByTestId("command-palette-input");
    fireEvent.change(input, { target: { value: "AA" } });
    await act(async () => { vi.advanceTimersByTime(260); });
    fireEvent.change(input, { target: { value: "BB" } });
    await act(async () => { vi.advanceTimersByTime(260); });
    await act(async () => { resolveB?.(mk("BB")); });
    expect(screen.getByTestId("palette-ticker-BB")).toBeInTheDocument();
    // 늦게 도착한 A 응답은 무시돼야 한다
    await act(async () => { resolveA?.(mk("AA")); });
    expect(screen.getByTestId("palette-ticker-BB")).toBeInTheDocument();
    expect(screen.queryByTestId("palette-ticker-AA")).not.toBeInTheDocument();
  });

  it("늦은 reject 가 최신 결과를 지우지 않는다 (codex P1)", async () => {
    vi.useFakeTimers();
    let rejectA: ((e: unknown) => void) | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn()
        .mockImplementationOnce(() => new Promise((_, rej) => { rejectA = rej; }))
        .mockImplementationOnce(() =>
          Promise.resolve({ ok: true, json: () => Promise.resolve({ results: [{ ticker: "BB", name: null, price: 1 }] }) }),
        ),
    );
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const input = screen.getByTestId("command-palette-input");
    fireEvent.change(input, { target: { value: "AA" } });
    await act(async () => { vi.advanceTimersByTime(260); });
    fireEvent.change(input, { target: { value: "BB" } });
    await act(async () => { vi.advanceTimersByTime(260); });
    expect(screen.getByTestId("palette-ticker-BB")).toBeInTheDocument();
    await act(async () => { rejectA?.(new Error("late")); });
    expect(screen.getByTestId("palette-ticker-BB")).toBeInTheDocument();
  });

  it("json 파싱 중 쿼리가 바뀌어도 낡은 본문은 폐기 (codex P1 — 2차 가드)", async () => {
    vi.useFakeTimers();
    let resolveJson: ((v: unknown) => void) | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn()
        .mockImplementationOnce(() =>
          Promise.resolve({ ok: true, json: () => new Promise((r) => { resolveJson = r; }) }),
        )
        .mockImplementationOnce(() =>
          Promise.resolve({ ok: true, json: () => Promise.resolve({ results: [{ ticker: "BB", name: null, price: 1 }] }) }),
        ),
    );
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const input = screen.getByTestId("command-palette-input");
    fireEvent.change(input, { target: { value: "AA" } });
    await act(async () => { vi.advanceTimersByTime(260); });
    // fetch 는 끝났지만 json 이 아직 — 이 사이 쿼리 변경
    fireEvent.change(input, { target: { value: "BB" } });
    await act(async () => { vi.advanceTimersByTime(260); });
    expect(screen.getByTestId("palette-ticker-BB")).toBeInTheDocument();
    await act(async () => { resolveJson?.({ results: [{ ticker: "AA", name: null, price: 1 }] }); });
    expect(screen.queryByTestId("palette-ticker-AA")).not.toBeInTheDocument();
    expect(screen.getByTestId("palette-ticker-BB")).toBeInTheDocument();
  });

  it("모달 안 Tab 은 갇힌다 (최소 포커스 트랩)", () => {
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const notPrevented = fireEvent.keyDown(screen.getByTestId("command-palette"), { key: "Tab" });
    expect(notPrevented).toBe(false); // preventDefault 호출됨
  });

  it("ok=false 응답은 이전 쿼리의 결과를 화면에 남기지 않는다 (codex P1)", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn()
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ results: [{ ticker: "AAA", name: null, price: 1 }] }) })
        .mockResolvedValueOnce({ ok: false, json: () => Promise.resolve({}) }),
    );
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const input = screen.getByTestId("command-palette-input");
    fireEvent.change(input, { target: { value: "AAA" } });
    await act(async () => { vi.advanceTimersByTime(260); });
    expect(screen.getByTestId("palette-ticker-AAA")).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "BBB" } });
    await act(async () => { vi.advanceTimersByTime(260); });
    expect(screen.queryByTestId("palette-ticker-AAA")).not.toBeInTheDocument();
  });

  it("결과 0건에서 ArrowDown 은 음수로 내려가지 않고, 이후 결과에서 Enter 가 산다 (codex P1)", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ results: [] }) }));
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const input = screen.getByTestId("command-palette-input");
    fireEvent.change(input, { target: { value: "zzz-none" } });
    await act(async () => { vi.advanceTimersByTime(260); });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    // 라우트가 다시 매칭되면 첫 항목이 선택돼 있어야 하고 Enter 가 동작해야 한다
    fireEvent.change(input, { target: { value: "deci" } });
    expect(screen.getByTestId("palette-route-/decisions")).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(pushMock).toHaveBeenCalledWith("/decisions");
  });

  it("한글 IME 조합 중 Enter 는 내비게이션하지 않는다 (codex P2)", () => {
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const input = screen.getByTestId("command-palette-input");
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    expect(pushMock).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(pushMock).toHaveBeenCalledTimes(1);
  });

  it("한글 IME 조합 중 Escape 는 조합 취소일 뿐 팔레트를 닫지 않는다 (codex R2)", () => {
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    fireEvent.keyDown(window, { key: "Escape", isComposing: true });
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("command-palette")).not.toBeInTheDocument();
  });

  it("닫히면 포커스가 트리거 버튼으로 복원 (codex P2)", () => {
    render(<CommandPalette />);
    const trigger = screen.getByTestId("palette-trigger");
    fireEvent.click(trigger);
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.activeElement).toBe(trigger);
  });

  it("aria-activedescendant 가 선택을 따라간다 (codex P2)", () => {
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const input = screen.getByTestId("command-palette-input");
    expect(input).toHaveAttribute("aria-activedescendant", "palette-opt-0");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input).toHaveAttribute("aria-activedescendant", "palette-opt-1");
  });

  it("접근성: dialog aria-label + option aria-selected", () => {
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.getByRole("dialog", { name: PALETTE.ARIA })).toBeInTheDocument();
    const options = screen.getAllByRole("option");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(options[1]).toHaveAttribute("aria-selected", "false");
  });
});
