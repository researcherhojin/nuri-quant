import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GenerateBriefing } from "@/app/ticker-next/[symbol]/generate-briefing";
import { FundBriefing } from "@/app/ticker-next/[symbol]/fund-briefing";
import { researchSchema } from "@/app/ticker-next/[symbol]/data";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import { PublicBriefing } from "@/app/ticker-next/[symbol]/public-briefing";
import { publicBriefingSchema } from "@/app/ticker-next/[symbol]/public-briefing-schema";
import type { TickerReview } from "@/app/ticker-next/[symbol]/data";

vi.mock("@/app/ticker-next/[symbol]/decision-briefing", () => ({ CurrentJudgment: () => <p>기존 시스템 판단</p>, PriceSummary: () => <p>저장된 가격</p> }));

vi.mock("@/app/ticker-next/[symbol]/financial-reading", () => ({ FinancialReading: () => <p>저장된 재무 자료</p> }));

const router = vi.hoisted(() => ({ refresh: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => router }));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

const data: TickerReview = { ticker: null, prices: null, history: null, actions: null, reviews: [], research: null };

const passage = { text: "생산 확대 계획은 실행 여부를 확인해야 합니다.", claim_ids: ["claim-plan"] };

const report = { summary: passage, business: passage, changes: passage, financials: passage, schedule: passage,
  arguments: [{ title: "생산 확대", fact: passage, impact: passage, counterpoint: passage, checkpoint: passage, timing: passage }] };

const briefing = publicBriefingSchema.parse({ status: "ready", report,
  claims: [{ claim_id: "claim-plan", source_id: "official", statement: "회사 생산 계획입니다.", kind: "plan", entity: "Demo Company", period: null }],
  sources: [{ source_id: "official", title: "공식 발표", url: "https://example.com/release", published_at: "2026-01-01", collected_at: "2026-01-02", entity: "Demo Company", kind: "official" }] });

describe("출처 기반 브리핑", () => {
  it("uses one report, ordered sections, balanced arguments and separate system verdict", () => {
    render(<PublicBriefing data={data} symbol="DEMO" briefing={briefing} />);
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getAllByRole("heading", { level: 2 }).map(node => node.textContent)).toEqual([T.DOCUMENT_TITLE, ...Object.values(T.DOCUMENT_SECTIONS)]);
    expect(screen.getByText(T.BRIEFING_COUNTER)).toBeTruthy();
    expect(screen.getByText("기존 시스템 판단")).toBeTruthy();
    expect(screen.getAllByText(/회사 계획/).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: /공식 발표/ })[0]).toHaveAttribute("href", "https://example.com/release");
  });

  it("does not display a rejected report", () => {
    render(<PublicBriefing data={data} symbol="DEMO" briefing={{ ...briefing, status: "invalid" }} />);
    expect(screen.queryByRole("article")).toBeNull();
  });
});


describe("브리핑 생성 요청", () => {
  it("starts only on click and refreshes after completed polling", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce({ ok: true }).mockResolvedValueOnce({ ok: true, json: async () => ({ public_briefing: { status: "ready" } }) });
    vi.stubGlobal("fetch", fetcher);
    render(<GenerateBriefing symbol="DEMO" />);
    expect(fetcher).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: T.BRIEFING_GENERATE }));
    await waitFor(() => expect(router.refresh).toHaveBeenCalledOnce());
    expect(fetcher).toHaveBeenNthCalledWith(1, "/api/ticker/DEMO/research/briefing", { method: "POST" });
    expect(fetcher).toHaveBeenNthCalledWith(2, "/api/ticker/DEMO/research", { cache: "no-store" });
  });

  it("shows busy rejection without starting polling", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 503 });
    vi.stubGlobal("fetch", fetcher);
    render(<GenerateBriefing symbol="DEMO" />);
    fireEvent.click(screen.getByRole("button", { name: T.BRIEFING_GENERATE }));
    await screen.findByRole("status");
    expect(screen.getByRole("status")).toHaveTextContent(T.BRIEFING_BUSY);
    expect(fetcher).toHaveBeenCalledOnce();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it.each([
    ["stale research (409)", { ok: false, status: 409 }, T.BRIEFING_STALE_DATA],
    ["any other HTTP failure", { ok: false, status: 500 }, T.BRIEFING_START_FAILED],
  ])("explains a rejected start for %s and lets the user try again", async (_, response, message) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    render(<GenerateBriefing symbol="DEMO" />);
    fireEvent.click(screen.getByRole("button", { name: T.BRIEFING_GENERATE }));
    expect(await screen.findByRole("status")).toHaveTextContent(message);
    expect(screen.getByRole("button", { name: T.BRIEFING_GENERATE })).toBeEnabled();
  });

  it("reports a start request that never reached the server and re-enables the button", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    render(<GenerateBriefing symbol="DEMO" />);
    fireEvent.click(screen.getByRole("button", { name: T.BRIEFING_GENERATE }));
    expect(await screen.findByRole("status")).toHaveTextContent(T.BRIEFING_START_FAILED);
    expect(screen.getByRole("button", { name: T.BRIEFING_GENERATE })).toBeEnabled();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("marks a finished briefing as done and does not offer to generate it again", () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    render(<GenerateBriefing symbol="DEMO" status="ready" />);
    expect(screen.getByRole("button", { name: T.BRIEFING_DONE })).toBeDisabled();
    expect(fetcher).not.toHaveBeenCalled();
  });
});

describe("브리핑 생성 폴링", () => {
  beforeEach(() => { vi.useFakeTimers(); });

  afterEach(() => { vi.useRealTimers(); });

  const pending = { ok: true, json: async () => ({ public_briefing: { status: "pending" } }) };

  async function advance(ms: number) {
    await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
  }

  it("keeps polling through a failed lookup and a still-pending briefing, and refreshes only once it is done", async () => {
    // 실패 응답의 본문이 우연히 "완료" 로 읽혀도 HTTP 실패는 완료가 아니다
    const failed = { ok: false, status: 500, json: async () => ({ public_briefing: null }) };
    const done = { ok: true, json: async () => ({ public_briefing: { status: "ready" } }) };
    const fetcher = vi.fn().mockResolvedValueOnce(failed).mockResolvedValueOnce(pending).mockResolvedValueOnce(done);

    vi.stubGlobal("fetch", fetcher);
    await act(async () => { render(<GenerateBriefing symbol="DEMO" status="pending" />); });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(router.refresh).not.toHaveBeenCalled();
    await advance(2500);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(router.refresh).not.toHaveBeenCalled();
    await advance(2500);
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(router.refresh).toHaveBeenCalledOnce();
    await advance(10_000);
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("stops polling after five minutes and tells the user to reload later", async () => {
    const fetcher = vi.fn().mockResolvedValue(pending);

    vi.stubGlobal("fetch", fetcher);
    await act(async () => { render(<GenerateBriefing symbol="DEMO" status="pending" />); });
    await advance(300_000);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await advance(5000);
    expect(screen.getByRole("status")).toHaveTextContent(T.BRIEFING_SLOW);
    const calls = fetcher.mock.calls.length;

    await advance(30_000);
    expect(fetcher).toHaveBeenCalledTimes(calls);
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("sends no further lookup once the component is gone, even if an in-flight lookup was still pending", async () => {
    let answer: (value: typeof pending) => void = () => {};

    const fetcher = vi.fn().mockReturnValueOnce(new Promise(resolve => { answer = resolve; }));

    vi.stubGlobal("fetch", fetcher);
    let view: ReturnType<typeof render> | undefined;

    await act(async () => { view = render(<GenerateBriefing symbol="DEMO" status="pending" />); });
    view?.unmount();
    await act(async () => { answer(pending); });
    await advance(10_000);
    expect(fetcher).toHaveBeenCalledOnce();
  });
});


describe("공통 종목 보고서", () => {
  it("uses identical section order and navigation for ETF and company reports", () => {
    const fundData: TickerReview = { ...data, research: researchSchema.parse({ ticker: "DEMO", today: "2026-01-02", collected_today: true, dossier: { ticker: "DEMO", collected_at: "2026-01-02", profile: { name: "Demo Fund", symbol: "DEMO", quote_type: "ETF" }, statements: { income: [], cashflow: [], balance: [] }, fund: { source_name: "Example Issuer", source_url: "https://example.com/fund", strategy_text: "공개 자료의 상품 설명", holdings: [], risks: [] } }, news: [], events: [], fundamentals_history: [] }) };

    for (const component of [<PublicBriefing key="company" data={data} symbol="DEMO" briefing={briefing} />, <FundBriefing key="fund" data={fundData} symbol="DEMO" />]) {
      const view = render(component);
      const article = screen.getByTestId("ticker-briefing");

      expect([...article.querySelectorAll(":scope > section > h2")].map(el => el.textContent)).toEqual(Object.values(T.DOCUMENT_SECTIONS));
      expect([...article.querySelectorAll(":scope > section")].map(el => el.id)).toEqual(Object.keys(T.DOCUMENT_SECTIONS).map(id => `research-${id}`));
      expect(screen.getByRole("navigation", { name: T.DOCUMENT_INDEX }).querySelectorAll("a")).toHaveLength(7);
      expect(screen.getByRole("heading", { name: T.DOCUMENT_TITLE })).toBeTruthy();
      view.unmount();
    }
  });
});
