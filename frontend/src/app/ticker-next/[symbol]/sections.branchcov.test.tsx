/**
 * 매매 판단 · 리서치 · 이력 탭과 판단 요약의 분기 잠금 — 자료가 "없음" 인지 "불러오지 못함" 인지,
 * 값이 비었을 때 무엇으로 대신하는지를 화면 문장으로 확인한다. 픽스처는 실제 스키마를 통과시킨다.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { z } from "zod";
import { Evidence, History, HoldingReview, Research } from "./sections";
import { CurrentJudgment, PriceSummary } from "./decision-briefing";
import { SourceDates } from "./source-dates";
import { historySchema, pricesSchema, researchSchema, tickerSchema, type TickerReview } from "./data";
import { actionsSchema } from "@/app/(overview)/data";
import { displayTime } from "@/app/(overview)/format";
import { CONSENSUS, OVERVIEW, TICKER_PREVIEW as T } from "@/lib/strings";
import { formatMoney, formatNum, formatPct } from "@/lib/format";

vi.mock("next/link", () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

vi.mock("@/components/ui/price-chart-lazy", () => ({ PriceChartLazy: () => <div>chart fixture</div> }));

afterEach(cleanup);

const empty: TickerReview = { ticker: null, prices: null, history: null, actions: null, reviews: [], research: null };

const ticker = (value: Record<string, unknown>) => tickerSchema.parse({ ticker: "DEMO", ...value });

function panel(title: string): HTMLElement {
  const found = screen.getByRole("heading", { name: title }).closest("section");

  if (!found) throw new Error(`panel ${title} missing`);

  return found;
}

function cells(root: HTMLElement): string[][] {
  return within(root).getAllByRole("row").slice(1).map(row => within(row).getAllByRole("cell").map(cell => cell.textContent ?? ""));
}

describe("HoldingReview", () => {
  it("says the review list is unavailable, not empty, when the actions request failed", () => {
    render(<HoldingReview data={empty} />);
    expect(screen.getByText(T.UNAVAILABLE)).toBeInTheDocument();
    expect(screen.queryByText(T.NO_REVIEW)).not.toBeInTheDocument();
    expect(screen.queryByText(T.GENERATED, { exact: false })).not.toBeInTheDocument();
  });

  it("keeps missing review fields visibly unknown instead of inventing them", () => {
    const actions = actionsSchema.extend({ generated_at: z.string() }).parse({
      urgent: [], check: [], hold: [], generated_at: "2026-01-06T09:00:00",
      portfolio: [{ ticker: "DEMO", action: "HOLD", confidence: null, reasons: [], position_pct: 12.5, pnl_pct: null, as_of: null, decision_id: null }],
    });

    render(<HoldingReview data={{ ...empty, actions, reviews: actions.portfolio.map(item => ({ ...item, bucket: "portfolio" as const })) }} />);
    const review = screen.getByRole("article");

    expect(within(review).getByText(OVERVIEW.INBOX_PANEL.BUCKETS.portfolio)).toBeInTheDocument();
    expect(within(review).getByText(`${T.REVIEW_DATE} · ${T.UNKNOWN_DATE}`)).toBeInTheDocument();
    expect(within(review).getByRole("listitem")).toHaveTextContent(T.NO_REASON);
    expect(within(review).getByText(`${formatNum(12.5)}%`)).toBeInTheDocument();
    expect(within(review).getByText(`${T.ACCOUNT} · ${T.NOT_PROVIDED}`)).toBeInTheDocument();
    expect(within(review).getByText(T.NO_LEDGER)).toBeInTheDocument();
    expect(within(review).queryByRole("link", { name: T.LEDGER })).not.toBeInTheDocument();
    expect(screen.getByText(`${T.GENERATED} · ${displayTime("2026-01-06T09:00:00")}`)).toBeInTheDocument();
  });
});

describe("Evidence", () => {
  it("hides stored verdicts and dissent of a consensus that reported an error", () => {
    render(<Evidence data={{ ...empty, ticker: ticker({ consensus: { error: "consensus failed", verdicts: [{ agent_name: "value", action: "BUY", reasoning: "Stale value reasoning" }], dissent: ["Stale dissent"] } }) }} />);
    expect(within(panel(T.DISSENT)).getByText(T.NO_CONSENSUS)).toBeInTheDocument();
    expect(within(panel(T.AGENTS)).getByText(T.NO_CONSENSUS)).toBeInTheDocument();
    expect(screen.queryByText("Stale value reasoning")).not.toBeInTheDocument();
    expect(screen.queryByText("Stale dissent")).not.toBeInTheDocument();
  });

  it("separates no dissent and no verdicts from a missing consensus", () => {
    render(<Evidence data={{ ...empty, ticker: ticker({ consensus: { final_action: "HOLD" } }) }} />);
    expect(within(panel(T.DISSENT)).getByText(T.NO_DISSENT)).toBeInTheDocument();
    expect(within(panel(T.AGENTS)).getByText(T.NO_DATA)).toBeInTheDocument();
    expect(screen.queryByText(T.NO_CONSENSUS)).not.toBeInTheDocument();
  });

  it("shows an abstaining agent as a placeholder with no score, and a missing reason as such", () => {
    render(<Evidence data={{ ...empty, ticker: ticker({ consensus: { final_action: "HOLD", verdicts: [{ agent_name: "macro", action: "HOLD", confidence: 77, abstained: true }] } }) }} />);
    const agent = within(panel(T.AGENTS)).getByText("macro").closest("details");

    if (!agent) throw new Error("agent row missing");
    expect(within(agent).getByText(CONSENSUS.PLACEHOLDER_ABSTAINED)).toBeInTheDocument();
    expect(within(agent).queryByText(CONSENSUS.PLACEHOLDER_DEGRADED)).not.toBeInTheDocument();
    expect(within(agent).queryByText("77")).not.toBeInTheDocument();
    expect(within(agent).getByText(T.NO_REASON)).toBeInTheDocument();
  });
});

describe("Research", () => {
  const tables = [T.RATINGS, T.EARNINGS, T.INSIDERS, T.INVESTORS];

  it("says every panel is unavailable when nothing could be loaded", () => {
    render(<Research symbol="DEMO" data={empty} />);
    expect(within(panel(T.PRICE_HISTORY)).getByText(T.UNAVAILABLE)).toBeInTheDocument();
    expect(within(panel(T.FUNDAMENTALS)).getByText(T.UNAVAILABLE)).toBeInTheDocument();
    expect(within(panel(T.FUNDAMENTALS)).getByText(`${T.DATE} · ${T.UNKNOWN_DATE}`)).toBeInTheDocument();

    for (const title of tables) expect(within(panel(title)).getByText(T.UNAVAILABLE)).toBeInTheDocument();
  });

  it("says no data, not unavailable, when the stored lists are empty", () => {
    render(<Research symbol="DEMO" data={{ ...empty, ticker: ticker({}), prices: pricesSchema.parse({ prices: [] }) }} />);
    expect(within(panel(T.PRICE_HISTORY)).getByText(T.NO_DATA)).toBeInTheDocument();
    expect(within(panel(T.FUNDAMENTALS)).getByText(T.NO_DATA)).toBeInTheDocument();

    for (const title of tables) {
      expect(within(panel(title)).getByText(T.NO_DATA)).toBeInTheDocument();
      expect(within(panel(title)).queryByText(T.UNAVAILABLE)).not.toBeInTheDocument();
    }
  });

  it("formats stored fundamentals and fills every missing table cell with a dash", () => {
    render(<Research symbol="DEMO" data={{ ...empty, ticker: ticker({
      fundamentals: { date: "2026-01-01", pe_ratio: 15, roe: 0.25, revenue_growth: null, debt_to_equity: 45, profit_margin: 0.5, beta: 1.2 },
      analyst_ratings: [
        { firm: "Example Research", date: null, to_grade: null, action: "init", target_price: 150 },
        { firm: "Sample Analytics", date: "2026-01-02", to_grade: "Overweight", action: "up", target_price: null },
        { firm: "Demo Desk", date: null, to_grade: null, action: null, target_price: null },
      ],
      earnings: [{ quarter: null, eps_actual: 1.234, eps_estimate: null }],
      insider_trades: [{ date: null, insider_name: null, transaction_type: null, shares: 1_000 }],
      superinvestors: [{ investor: "Example Fund LP", portfolio_pct: null, filing_date: null }, { investor: "Sample Capital", portfolio_pct: 4.5, filing_date: "2025-12-31" }],
    }) }} />);
    const fundamentals = Object.fromEntries([...panel(T.FUNDAMENTALS).querySelectorAll("dt")].map(term => [term.textContent, term.nextElementSibling?.textContent]));

    expect(fundamentals).toEqual({
      [T.FUND_LABELS.pe_ratio]: formatNum(15), [T.FUND_LABELS.roe]: formatPct(25), [T.FUND_LABELS.revenue_growth]: "—",
      [T.FUND_LABELS.debt_to_equity]: formatPct(45), [T.FUND_LABELS.profit_margin]: formatPct(50), [T.FUND_LABELS.beta]: formatNum(1.2),
    });
    expect(within(panel(T.FUNDAMENTALS)).getByText(`${T.DATE} · 2026-01-01`)).toBeInTheDocument();
    expect(cells(panel(T.RATINGS))).toEqual([
      ["Example Research", "—", "init", formatMoney(150, { ticker: "DEMO" })],
      ["Sample Analytics", "2026-01-02", "Overweight", "—"],
      ["Demo Desk", "—", "—", "—"],
    ]);
    expect(cells(panel(T.EARNINGS))).toEqual([["—", formatNum(1.234, 2), "—"]]);
    expect(cells(panel(T.INSIDERS))).toEqual([["—", "—", "—", formatNum(1_000, 0)]]);
    expect(cells(panel(T.INVESTORS))).toEqual([["Example Fund LP", "—", "—"], ["Sample Capital", "2025-12-31", `${formatNum(4.5)}%`]]);
  });
});

describe("History", () => {
  it("says the ledger is unavailable when the request failed, and empty when it returned nothing", () => {
    render(<History data={empty} />);
    expect(screen.getByText(T.UNAVAILABLE)).toBeInTheDocument();
    cleanup();
    render(<History data={{ ...empty, history: historySchema.parse({ decisions: [] }) }} />);
    expect(screen.getByText(T.NO_DATA)).toBeInTheDocument();
    expect(screen.queryByText(T.UNAVAILABLE)).not.toBeInTheDocument();
  });

  it("shows unknown outcome codes as stored, a dash without an outcome, and the latest change of call", () => {
    const history = historySchema.parse({ decisions: [
      { id: 7, ticker: "DEMO", date: "2026-01-03", action: "SELL", outcome: "partially_tracked", reasoning: null },
      { id: 6, ticker: "DEMO", date: "2026-01-02", action: "HOLD", outcome: null, reasoning: "Earlier stored reason" },
    ] });

    render(<History data={{ ...empty, history }} />);
    expect(screen.getByText(T.HISTORY_CHANGE("HOLD", "SELL"))).toBeInTheDocument();
    const latest = screen.getByRole("article", { name: `2026-01-03 ${T.HISTORY}` });
    const previous = screen.getByRole("article", { name: `2026-01-02 ${T.HISTORY}` });
    const outcome = (root: HTMLElement) => within(root).getByText(T.OUTCOME).nextElementSibling?.textContent;

    expect(outcome(latest)).toBe("partially_tracked");
    expect(within(latest).getByText(T.NO_REASON)).toBeInTheDocument();
    expect(outcome(previous)).toBe("—");
  });
});

describe("CurrentJudgment", () => {
  const judge = (consensus: Record<string, unknown>, compact = false) =>
    render(<CurrentJudgment compact={compact} data={{ ...empty, ticker: ticker({ consensus }) }} />);

  it("flags a legacy risk reason computed before the position basis existed", () => {
    judge({ final_action: "SELL", verdicts: [{ agent_name: "risk", action: "SELL", reasoning: "보유 비중 초과 (12%)", data_points: null }] });
    expect(screen.getByRole("note")).toHaveTextContent(T.LEGACY_CALCULATION_NOTE);
  });

  it("does not flag the same risk reason once its position basis is recorded", () => {
    judge({ final_action: "SELL", verdicts: [{ agent_name: "risk", action: "SELL", reasoning: "보유 비중 초과 (12%)", data_points: { position_basis: "market_value" } }] });
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("keeps the stored order of supporting reasons when the result is not a risk veto", () => {
    judge({ final_action: "BUY", scoring_detail: { final_action_source: "weighted_sum" }, verdicts: [
      { agent_name: "technical", action: "BUY", reasoning: "Technical support reason" },
      { agent_name: "risk", action: "BUY", reasoning: "Risk support reason" },
    ] });
    const reasons = within(screen.getByRole("heading", { name: T.PRO_REASONS }).parentElement ?? document.body).getAllByRole("listitem");

    expect(reasons.map(item => item.textContent)).toEqual(["Technical support reason · technical", "Risk support reason · risk"]);
    expect(screen.getByText(T.DECISION_MECHANISMS.weighted_sum)).toBeInTheDocument();
  });

  it("says no valid reason exists when the consensus carries no verdicts", () => {
    judge({ final_action: "HOLD" }, true);
    expect(screen.getByText(T.NO_VALID_REASON)).toBeInTheDocument();
  });
});

describe("PriceSummary", () => {
  const flat = pricesSchema.parse({ prices: [
    { date: "2026-01-02", open: 10, high: 10, low: 10, close: 10, volume: 100 },
    { date: "2026-01-05", open: 10, high: 10, low: 10, close: 10, volume: 200 },
  ] });

  it("draws a flat trend line instead of NaN coordinates when every close is equal", () => {
    const { container } = render(<PriceSummary compact symbol="DEMO" data={{ ...empty, prices: flat }} />);

    expect(container.querySelector("polyline")?.getAttribute("points")).toBe("20,160 580,160");
    expect(screen.getByRole("img", { name: T.PRICE_TREND("2026-01-02", "2026-01-05") })).toBeInTheDocument();
  });

  it("credits the stored system price, not Yahoo, when no collected price history exists", () => {
    render(<PriceSummary symbol="DEMO" data={{ ...empty, prices: flat }} />);
    expect(screen.getByText(T.STORED_PRICE_SOURCE)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});

describe("SourceDates", () => {
  it("names each source that could not be collected and marks unknown source keys as not provided", () => {
    const research = researchSchema.parse({ ticker: "DEMO", news: [], events: [], fundamentals_history: [], dossier: {
      ticker: "DEMO", collected_at: "2026-01-06T09:00:00+09:00", unavailable: ["news", "unlisted_feed"],
      profile: { name: "Demo Company", symbol: "DEMO" }, statements: { income: [], cashflow: [], balance: [] },
    } });

    render(<SourceDates data={{ ...empty, research }} />);
    expect(screen.getByText(`${T.MISSING_SOURCES} · ${T.SOURCE_FIELDS.news} · ${T.NOT_PROVIDED}`)).toBeInTheDocument();
  });

  it("shows no missing-source notice when every source was collected", () => {
    render(<SourceDates data={empty} />);
    expect(screen.queryByText(T.MISSING_SOURCES, { exact: false })).not.toBeInTheDocument();
  });
});
