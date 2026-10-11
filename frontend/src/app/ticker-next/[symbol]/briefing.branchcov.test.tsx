/**
 * 종목 브리핑(회사형) 분기 잠금 — #1735 미리보기의 codecov/patch 부채.
 *
 * `financial-reading.tsx` 는 죽은 코드가 아니다: `briefing.tsx` 가 사업 자료(`dossier.business`)가
 * 있을 때, `public-briefing.tsx` 가 실적 절에서 렌더한다. 기존 `public-briefing.test.tsx` 는 그것을
 * mock 으로 바꿔 끼워 실제 해석 문장이 한 번도 검사되지 않았다 — 여기서는 mock 없이 본다.
 * 픽스처는 전부 실제 zod 스키마(`researchSchema` · `publicBriefingSchema`)를 통과시킨다.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { Briefing, StockDetails } from "./briefing";
import { FinancialReading } from "./financial-reading";
import { PublicBriefing } from "./public-briefing";
import { NewsItem } from "./news-item";
import { researchSchema, type TickerReview } from "./data";
import { publicBriefingSchema } from "./public-briefing-schema";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import { formatNum, formatPct } from "@/lib/format";
import { displayTime } from "@/app/(overview)/format";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

afterEach(cleanup);

const PERIOD = "2025-12-31";

const PREVIOUS = "2024-12-31";

const empty: TickerReview = { ticker: null, prices: null, history: null, actions: null, reviews: [], research: null };

function dossier(extra: Record<string, unknown> = {}) {
  return {
    ticker: "DEMO", collected_at: "2026-01-06T09:00:00+09:00",
    profile: { name: "Demo Company", symbol: "DEMO", financial_currency: "USD" },
    statements: { income: [], cashflow: [], balance: [] },
    ...extra,
  };
}

function withResearch(value: Record<string, unknown> | null, extra: Record<string, unknown> = {}): TickerReview {
  return { ...empty, research: researchSchema.parse({ ticker: "DEMO", news: [], events: [], fundamentals_history: [], dossier: value, ...extra }) };
}

function statements(income: Record<string, unknown>[], cashflow: Record<string, unknown>[] = [], balance: Record<string, unknown>[] = []) {
  return { income, cashflow, balance };
}

function panel(title: string): HTMLElement {
  const found = screen.getByRole("heading", { name: title }).closest("section");

  if (!found) throw new Error(`panel ${title} missing`);

  return found;
}

function reportSection(id: keyof typeof T.DOCUMENT_SECTIONS): HTMLElement {
  const found = screen.getByRole("heading", { level: 2, name: T.DOCUMENT_SECTIONS[id] }).closest("section");

  if (!found) throw new Error(`section ${id} missing`);

  return found;
}

function paragraphs(root: HTMLElement, skip: readonly string[] = []): string[] {
  return [...root.querySelectorAll("p")].flatMap(node => {
    const text = node.textContent ?? "";

    return skip.includes(text) ? [] : [text];
  });
}

const business = {
  summary: "Demo Company designs widgets for factories.", sector_label: "Industrial equipment", industry_label: "Widgets",
  has_financing: false, source_name: "Example Registry", source_url: "https://example.com/registry",
  activities: [{ title: "Widget sales", explanation: "Sells widgets to factory operators.", checkpoint: "Order backlog", source_phrase: "designs and sells widgets" }],
};

describe("Briefing — research unavailable", () => {
  it("says the company, news and financial panels are unavailable instead of empty, and still offers generation", () => {
    render(<Briefing data={empty} symbol="DEMO" />);
    expect(within(panel(T.COMPANY)).getByText(T.UNAVAILABLE)).toBeInTheDocument();
    expect(within(panel(T.RECENT)).getByText(T.UNAVAILABLE)).toBeInTheDocument();
    expect(within(panel(T.RECENT)).queryByText(T.NEWS_NOT_CHECKED)).not.toBeInTheDocument();
    expect(within(panel(T.BRIEF_FACTS)).getByText(T.NO_FINANCIALS)).toBeInTheDocument();
    expect(within(panel(T.BRIEF_FACTS)).getByText(T.CURRENCY_UNKNOWN)).toBeInTheDocument();
    expect(within(reportSection("summary")).getByText(T.NO_PROFILE)).toBeInTheDocument();
    expect(within(reportSection("schedule")).getByText(T.DOCUMENT_NO_SCHEDULE)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: T.BRIEFING_GENERATE })).toBeEnabled();
  });
});

describe("Briefing — company profile with a business summary", () => {
  it("reads financials through FinancialReading and turns business activities into checkpoints", () => {
    render(<Briefing symbol="DEMO" data={withResearch(dossier({
      profile: { name: "Demo Company", display_name: "Demo Display", symbol: "DEMO", exchange: "KSC", country: "South Korea", website: "https://example.com", description: "Short source description.", financial_currency: "KRW" },
      business,
      statements: statements([{ period: PERIOD, revenue: 2_000_000, operating_income: 400_000, net_income: 300_000 }]),
    }))} />);
    const company = panel(T.COMPANY);

    expect(within(company).getByRole("heading", { name: "Demo Display" })).toBeInTheDocument();
    expect(within(company).getByText(business.summary)).toBeInTheDocument();
    expect(within(company).getByText(T.COUNTRY_KR)).toBeInTheDocument();
    expect(within(company).getByRole("heading", { name: T.BUSINESS_CORE })).toBeInTheDocument();
    expect(within(company).getByRole("heading", { name: "Widget sales" })).toBeInTheDocument();
    expect(within(company).getByText(`${T.SOURCE} · designs and sells widgets`)).toBeInTheDocument();
    // 한국어 사업 요약이 있으면 원문 발췌로 대신하지 않는다
    expect(within(company).queryByRole("heading", { name: T.BUSINESS_EXCERPT })).not.toBeInTheDocument();
    expect(within(company).getByRole("link", { name: T.WEBSITE })).toHaveAttribute("href", "https://example.com/");
    expect(within(reportSection("summary")).getByText(business.summary)).toBeInTheDocument();
    // 사업 자료가 있으면 사실 나열이 아니라 해석 패널(FinancialReading)로 읽는다
    const points = panel(T.BRIEF_FACTS);

    expect(within(points).getByRole("heading", { name: T.GROWTH_QUALITY })).toBeInTheDocument();
    expect(within(points).queryByText(T.SUMMARY_PROFIT(PERIOD, "300,000 KRW"))).not.toBeInTheDocument();
    const checkpoints = within(panel(T.RISK_FACTS)).getAllByRole("listitem").map(item => item.textContent);

    expect(checkpoints).toContain("Widget sales · Order backlog");
    expect(checkpoints).not.toContain(T.QUESTIONS[0]);
  });

  it("falls back to a trimmed source excerpt when the business summary is missing", () => {
    const description = Array.from({ length: 80 }, (_, index) => `segment${index}`).join(" ");

    render(<Briefing symbol="DEMO" data={withResearch(dossier({ profile: { name: "Demo Company", symbol: "DEMO", description, financial_currency: "USD" } }))} />);
    const excerpt = within(panel(T.COMPANY)).getByRole("heading", { name: T.BUSINESS_EXCERPT }).nextElementSibling?.textContent ?? "";

    expect(description.length).toBeGreaterThan(420);
    expect(excerpt.endsWith("…")).toBe(true);
    expect(excerpt.length).toBeLessThanOrEqual(421);
    // 단어 중간에서 자르지 않는다 — 원문에서 발췌 바로 뒤는 공백이다
    const kept = excerpt.slice(0, -1);

    expect(description.startsWith(kept)).toBe(true);
    expect(description[kept.length]).toBe(" ");
    expect(within(panel(T.COMPANY)).getByText(T.BUSINESS_PARTIAL)).toBeInTheDocument();
    expect(within(panel(T.COMPANY)).getByText(description)).toBeInTheDocument();
  });
});

describe("Briefing — stored financial facts without a business profile", () => {
  const usd = (value: string) => `${value} USD`;

  const cases: { name: string; data: ReturnType<typeof statements>; facts: string[]; risks?: string[] }[] = [
    {
      name: "every fact when both periods, cash flow and balance are complete",
      data: statements(
        [{ period: PERIOD, revenue: 1_200_000, net_income: 300_000 }, { period: PREVIOUS, revenue: 1_000_000 }],
        [{ period: PERIOD, operating_cashflow: 600_000, free_cashflow: 400_000 }],
        [{ period: PERIOD, cash: 2_000_000, debt: 1_000_000 }],
      ),
      facts: [
        T.SUMMARY_REVENUE(PERIOD, usd("1,200,000"), formatPct(20)),
        T.SUMMARY_PROFIT(PERIOD, usd("300,000")),
        T.SUMMARY_CASHFLOW(PERIOD, usd("600,000"), usd("400,000")),
        T.MARGIN_EXPLAIN(PERIOD, formatPct(25)),
        T.CASH_CONVERSION(PERIOD, formatNum(2, 2)),
        T.CASH_COMPARE(PERIOD, usd("2,000,000"), usd("1,000,000")),
      ],
    },
    {
      name: "no growth rate or margin without a previous period and a net income",
      data: statements([{ period: PERIOD, revenue: 1_000_000, net_income: null }]),
      facts: [T.SUMMARY_REVENUE(PERIOD, usd("1,000,000"), null)],
    },
    {
      name: "no growth rate when the previous revenue is zero",
      data: statements([{ period: PERIOD, revenue: 1_000_000 }, { period: PREVIOUS, revenue: 0 }]),
      facts: [T.SUMMARY_REVENUE(PERIOD, usd("1,000,000"), null)],
    },
    {
      name: "a cash-flow fact from free cash flow alone, and no conversion without operating cash flow",
      data: statements([{ period: PERIOD, net_income: 300_000 }], [{ period: PERIOD, operating_cashflow: null, free_cashflow: 100_000 }]),
      facts: [T.SUMMARY_PROFIT(PERIOD, usd("300,000")), T.SUMMARY_CASHFLOW(PERIOD, "—", usd("100,000"))],
    },
    {
      name: "no cash-flow fact when both cash-flow values are missing",
      data: statements([], [{ period: PERIOD, operating_cashflow: null, free_cashflow: null }]),
      facts: [],
    },
    {
      name: "no cash conversion across different report periods",
      data: statements([{ period: PERIOD, net_income: 300_000 }], [{ period: "2025-06-30", operating_cashflow: 600_000, free_cashflow: null }]),
      facts: [T.SUMMARY_PROFIT(PERIOD, usd("300,000")), T.SUMMARY_CASHFLOW("2025-06-30", usd("600,000"), "—")],
    },
    {
      name: "no cash conversion for a loss year, which is flagged as a risk instead",
      data: statements([{ period: PERIOD, net_income: -100_000 }], [{ period: PERIOD, operating_cashflow: 600_000, free_cashflow: null }]),
      facts: [T.SUMMARY_PROFIT(PERIOD, usd("-100,000")), T.SUMMARY_CASHFLOW(PERIOD, usd("600,000"), "—")],
      risks: [T.LOSS_FACT],
    },
    {
      name: "no cash comparison when the debt is missing",
      data: statements([], [], [{ period: PERIOD, cash: 1_000_000, debt: null }]),
      facts: [],
    },
  ];

  it.each(cases)("$name", ({ data, facts, risks }) => {
    render(<Briefing symbol="DEMO" data={withResearch(dossier({ statements: data }))} />);
    const points = panel(T.BRIEF_FACTS);

    expect(paragraphs(points, [T.FINANCIAL_NOTE])).toEqual(facts.length ? facts : [T.NO_FINANCIALS]);
    expect(within(points).queryByText(/null|undefined/)).not.toBeInTheDocument();
    expect(within(panel(T.RISK_FACTS)).getAllByRole("listitem").map(item => item.textContent)).toEqual(expect.arrayContaining(risks ?? [T.NO_RISK_FACT]));
  });
});

describe("Briefing — recent news and schedule", () => {
  const check = (failed: string[]) => ({ checked_at: "2026-01-06T09:00:00+09:00", window_start: "2025-12-07", window_end: "2026-01-06", sources: ["Feed A", "Feed B"], failed_sources: failed });

  const article = (index: number) => ({ date: `2026-01-0${index}`, title: `Headline ${index}`, source: "Example Wire", url: `https://example.com/${index}` });

  it("separates a search where every source failed from an empty search", () => {
    render(<Briefing symbol="DEMO" data={withResearch(dossier({ news: [], news_check: check(["Feed A", "Feed B"]) }))} />);
    const news = panel(T.RECENT);

    expect(within(news).getByText(T.NEWS_SOURCE_FAILED("Feed A · Feed B"))).toBeInTheDocument();
    expect(within(news).getByText(T.NEWS_SEARCH_FAILED)).toBeInTheDocument();
    expect(within(news).queryByText(T.NEWS_NONE_RECENT)).not.toBeInTheDocument();
  });

  it("shows three articles, folds the rest, names the failed source and lists dated events with fallbacks", () => {
    const events = [{ date: "2026-02-01", event_type: "earnings", description: "Quarterly results call" }, { date: "2026-03-01", event_type: null, description: null }];

    render(<Briefing symbol="DEMO" data={withResearch(dossier({ news: [1, 2, 3, 4, 5].map(article), news_check: check(["Feed B"]) }), { events })} />);
    const changes = reportSection("changes");

    expect(within(changes).getByText(T.NEWS_SOURCE_FAILED("Feed B"))).toBeInTheDocument();
    expect(within(changes).queryByText(T.NEWS_SEARCH_FAILED)).not.toBeInTheDocument();
    const more = within(changes).getByText(T.MORE_NEWS(2)).closest("details");

    if (!more) throw new Error("more-news disclosure missing");
    expect(within(more).getAllByRole("link").map(link => link.textContent)).toEqual(["Headline 4", "Headline 5"]);
    expect(within(changes).getAllByRole("link").map(link => link.textContent).slice(0, 3)).toEqual(["Headline 1", "Headline 2", "Headline 3"]);
    expect(within(changes).getByText("2026-02-01 · earnings")).toBeInTheDocument();
    expect(within(changes).getByText(`2026-03-01 · ${T.NOT_PROVIDED}`)).toBeInTheDocument();
    expect(within(changes).getByText(T.NOT_PROVIDED, { selector: "p" })).toBeInTheDocument();
    const schedule = reportSection("schedule");

    expect(paragraphs(schedule)).toEqual(["2026-02-01 · Quarterly results call", `2026-03-01 · ${T.NOT_PROVIDED}`]);
  });
});

describe("Briefing — public briefing routing", () => {
  const passage = { text: "Summary passage from public sources.", claim_ids: [] };

  const report = { summary: passage, business: passage, changes: passage, financials: passage, schedule: passage, arguments: [] };

  it("shows the generated report only when it is ready and has a report body", () => {
    render(<Briefing symbol="DEMO" data={withResearch(dossier(), { public_briefing: { status: "ready", model: "demo-model", report } })} />);
    expect(screen.getByText(T.BRIEFING_FOOTER("demo-model"))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: T.BRIEFING_GENERATE })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: T.COMPANY })).not.toBeInTheDocument();
  });

  it("falls back to the stored-facts layout when a ready status carries no report", () => {
    render(<Briefing symbol="DEMO" data={withResearch(dossier(), { public_briefing: { status: "ready", model: "demo-model" } })} />);
    expect(screen.queryByText(T.BRIEFING_FOOTER("demo-model"))).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: T.COMPANY })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: T.BRIEFING_DONE })).toBeDisabled();
  });
});

describe("StockDetails", () => {
  it("lists stored valuation snapshots and omits the source link without a dossier", () => {
    render(<StockDetails symbol="DEMO" data={withResearch(null, { fundamentals_history: [{ date: "2025-12-31", pe_ratio: 20, forward_pe: 18.5, price_to_book: null }] })} />);
    expect(within(panel(T.FINANCIAL_TREND)).getByText(T.NO_FINANCIALS)).toBeInTheDocument();
    expect(within(panel(T.FINANCIAL_TREND)).queryByRole("link")).not.toBeInTheDocument();
    const row = within(panel(T.VALUATION)).getByRole("row", { name: /^2025-12-31/ });

    expect(within(row).getAllByRole("cell").map(cell => cell.textContent)).toEqual(["2025-12-31", formatNum(20), formatNum(18.5), "—"]);
  });
});

describe("FinancialReading", () => {
  function show(value: Record<string, unknown> | null) {
    render(<FinancialReading data={value ? withResearch(value) : empty} />);
  }

  function block(heading: string): HTMLElement {
    const found = screen.getByRole("heading", { name: heading }).closest("section");

    if (!found) throw new Error(`${heading} block missing`);

    return found;
  }

  const growthCases: { name: string; income: Record<string, unknown>; previous?: Record<string, unknown>; sentences: string[] }[] = [
    {
      name: "revenue and operating income grow together",
      income: { period: PERIOD, revenue: 1_200_000, operating_income: 300_000 }, previous: { period: PREVIOUS, revenue: 1_000_000, operating_income: 200_000 },
      sentences: [T.PROFIT_CHANGE(PERIOD, formatPct(20), formatPct(50)), T.PROFITABILITY_CHANGE(formatPct(20), formatPct(25)), T.GROWTH_TOGETHER],
    },
    {
      name: "revenue grows while operating income falls",
      income: { period: PERIOD, revenue: 1_200_000, operating_income: 300_000 }, previous: { period: PREVIOUS, revenue: 1_000_000, operating_income: 400_000 },
      sentences: [T.PROFIT_CHANGE(PERIOD, formatPct(20), formatPct(-25)), T.PROFITABILITY_CHANGE(formatPct(40), formatPct(25)), T.GROWTH_DIVERGENCE],
    },
    {
      name: "both shrink — change is reported without a growth reading",
      income: { period: PERIOD, revenue: 800_000, operating_income: 100_000 }, previous: { period: PREVIOUS, revenue: 1_000_000, operating_income: 200_000 },
      sentences: [T.PROFIT_CHANGE(PERIOD, formatPct(-20), formatPct(-50)), T.PROFITABILITY_CHANGE(formatPct(20), formatPct(12.5))],
    },
    { name: "no previous period", income: { period: PERIOD, revenue: 1_200_000, operating_income: 300_000 }, sentences: [] },
    {
      name: "previous revenue missing",
      income: { period: PERIOD, revenue: 1_200_000, operating_income: 300_000 }, previous: { period: PREVIOUS, revenue: null, operating_income: 200_000 }, sentences: [],
    },
    {
      name: "previous revenue zero",
      income: { period: PERIOD, revenue: 1_200_000, operating_income: 300_000 }, previous: { period: PREVIOUS, revenue: 0, operating_income: 200_000 }, sentences: [],
    },
    {
      name: "current revenue missing",
      income: { period: PERIOD, revenue: null, operating_income: 300_000 }, previous: { period: PREVIOUS, revenue: 1_000_000, operating_income: 200_000 }, sentences: [],
    },
    {
      name: "current operating income missing",
      income: { period: PERIOD, revenue: 1_200_000, operating_income: null }, previous: { period: PREVIOUS, revenue: 1_000_000, operating_income: 200_000 }, sentences: [],
    },
    {
      name: "previous operating income missing",
      income: { period: PERIOD, revenue: 1_200_000, operating_income: 300_000 }, previous: { period: PREVIOUS, revenue: 1_000_000, operating_income: null }, sentences: [],
    },
    {
      name: "previous operating loss — margin change only, no profit growth rate",
      income: { period: PERIOD, revenue: 1_200_000, operating_income: 300_000 }, previous: { period: PREVIOUS, revenue: 1_000_000, operating_income: -100_000 },
      sentences: [T.PROFITABILITY_CHANGE(formatPct(-10), formatPct(25))],
    },
    {
      name: "current revenue zero — growth rates without a current margin",
      income: { period: PERIOD, revenue: 0, operating_income: 300_000 }, previous: { period: PREVIOUS, revenue: 1_000_000, operating_income: 200_000 },
      sentences: [T.PROFIT_CHANGE(PERIOD, formatPct(-100), formatPct(50))],
    },
  ];

  it.each(growthCases)("growth and profitability: $name", ({ income, previous, sentences }) => {
    show(dossier({ statements: statements(previous ? [income, previous] : [income]) }));
    expect(paragraphs(block(T.GROWTH_QUALITY), [`${T.PERIOD} · ${PERIOD}`])).toEqual(sentences);
  });

  it("shows the latest period's figures in compact form with the reporting currency", () => {
    show(dossier({ statements: statements([{ period: PERIOD, revenue: 1_200_000, operating_income: 300_000, net_income: 50_000 }]) }));
    const values = within(block(T.GROWTH_QUALITY)).getAllByRole("definition").map(node => node.textContent);

    expect(values).toEqual(["120만 USD", "30만 USD", "50,000 USD"]);
  });

  // 10만 미만은 전체 자릿수, 이상은 축약 표기 — 두 경로가 한 문장에 같이 나온다
  const outflow = { operating_cashflow: -50_000, free_cashflow: -200_000 };

  const cashCases: { name: string; income: Record<string, unknown>[]; cash: Record<string, unknown>; ocf: string; financing?: boolean; extra: string[] }[] = [
    { name: "profit without cash inflow in the same period", income: [{ period: PERIOD, net_income: 300_000 }], cash: { period: PERIOD, ...outflow }, ocf: "-50,000 USD", extra: [T.PROFIT_CASH_DIVERGENCE] },
    { name: "different report periods", income: [{ period: PERIOD, net_income: 300_000 }], cash: { period: "2025-06-30", ...outflow }, ocf: "-50,000 USD", extra: [] },
    { name: "net income missing", income: [{ period: PERIOD, net_income: null }], cash: { period: PERIOD, ...outflow }, ocf: "-50,000 USD", extra: [] },
    { name: "a loss year", income: [{ period: PERIOD, net_income: -100_000 }], cash: { period: PERIOD, ...outflow }, ocf: "-50,000 USD", extra: [] },
    { name: "operating cash flow missing", income: [{ period: PERIOD, net_income: 300_000 }], cash: { period: PERIOD, ...outflow, operating_cashflow: null }, ocf: "—", extra: [] },
    { name: "positive operating cash flow", income: [{ period: PERIOD, net_income: 300_000 }], cash: { period: PERIOD, ...outflow, operating_cashflow: 50_000 }, ocf: "50,000 USD", extra: [] },
    { name: "no income statement", income: [], cash: { period: PERIOD, ...outflow }, ocf: "-50,000 USD", extra: [] },
    { name: "a consolidated financing business", income: [{ period: PERIOD, net_income: 300_000 }], cash: { period: PERIOD, ...outflow, operating_cashflow: 50_000 }, ocf: "50,000 USD", financing: true, extra: [T.FINANCING_CONTEXT] },
    { name: "a business profile without financing", income: [{ period: PERIOD, net_income: 300_000 }], cash: { period: PERIOD, ...outflow, operating_cashflow: 50_000 }, ocf: "50,000 USD", financing: false, extra: [] },
  ];

  it.each(cashCases)("cash quality: $name", ({ income, cash, ocf, financing, extra }) => {
    const value: Record<string, unknown> = { statements: statements(income, [cash]) };

    if (financing != null) value.business = { ...business, has_financing: financing };

    show(dossier(value));
    expect(paragraphs(block(T.CASH_QUALITY))).toEqual([T.SUMMARY_CASHFLOW(String(cash.period), ocf, "-20만 USD"), ...extra]);
  });

  it("compares cash with debt for the balance-sheet period and needs no other statement", () => {
    show(dossier({ statements: statements([], [], [{ period: PERIOD, cash: 2_000_000, debt: 1_000_000 }]) }));
    expect(paragraphs(block(T.FUNDING_STRUCTURE))).toEqual([T.CASH_COMPARE(PERIOD, "200만 USD", "100만 USD")]);
    expect(screen.queryByRole("heading", { name: T.GROWTH_QUALITY })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: T.CASH_QUALITY })).not.toBeInTheDocument();
    expect(screen.queryByText(T.NO_FINANCIALS)).not.toBeInTheDocument();
  });

  it.each([["an empty statement set", dossier()], ["missing research", null]])("says there are no annual figures for %s", (_, value) => {
    show(value);
    expect(screen.getByText(T.NO_FINANCIALS)).toBeInTheDocument();
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });
});

describe("PublicBriefing — header, evidence and stored financials", () => {
  const passage = (text: string, claims: string[] = []) => ({ text, claim_ids: claims });

  const report = {
    summary: passage("Summary passage", ["claim-1"]), business: passage("Business passage"), changes: passage("Changes passage"),
    financials: passage("Financials passage"), schedule: passage("Schedule passage"), arguments: [],
  };

  const collected = "2026-01-02T09:00:00+09:00";

  function evidence(text: string): HTMLElement {
    const details = screen.getByText(text).nextElementSibling;

    if (!(details instanceof HTMLElement)) throw new Error(`${text} evidence missing`);

    return details;
  }

  it("says how much official material backed the report, how many claims were dropped, and dates undated sources", () => {
    const briefing = publicBriefingSchema.parse({
      status: "ready", model: "demo-model", collected_at: collected, generated_at: "2026-01-02T10:00:00+09:00", report,
      coverage: { official: 0, news: 2, snapshot: 1 }, rejected_claim_count: 2,
      claims: [{ claim_id: "claim-1", source_id: "source-1", statement: "Revenue grew in the fiscal year.", kind: "fact", entity: "Demo Company", period: "FY2025" }],
      sources: [{ source_id: "source-1", url: "https://example.com/article", title: "Example article", published_at: null, collected_at: collected, entity: "Demo Company", kind: "news" }],
    });

    const data = withResearch(dossier({
      profile: { name: "Demo Company", symbol: "DEMO", description: "Provider business description.", financial_currency: "USD" },
      statements: statements([{ period: PERIOD, revenue: 1_200_000, operating_income: 300_000 }]),
    }));

    render(<PublicBriefing data={data} symbol="DEMO" briefing={briefing} />);
    expect(screen.getByText(T.BRIEFING_COVERAGE(0, 2, 1) + T.BRIEFING_NO_IR)).toBeInTheDocument();
    expect(screen.getByText(T.BRIEFING_REJECTED(2) + T.BRIEFING_CHECKED)).toBeInTheDocument();
    const claim = evidence("Summary passage");

    expect(claim).toHaveTextContent(`${T.BRIEFING_KINDS.fact} · Demo Company · FY2025`);
    expect(within(claim).getByRole("link")).toHaveTextContent(`Example article · ${T.BRIEFING_UNDATED(displayTime(collected))}`);
    expect(within(reportSection("business")).getByText(T.BUSINESS_ORIGINAL)).toBeInTheDocument();
    expect(within(reportSection("financials")).getByRole("heading", { name: T.GROWTH_QUALITY })).toBeInTheDocument();
  });

  it("leaves out the no-IR note, the rejection count, evidence and the original description when there is nothing to show", () => {
    const briefing = publicBriefingSchema.parse({ status: "ready", model: "demo-model", report, coverage: { official: 1, news: 0, snapshot: 0 } });

    render(<PublicBriefing data={withResearch(dossier())} symbol="DEMO" briefing={briefing} />);
    expect(screen.getByText(T.BRIEFING_COVERAGE(1, 0, 0))).toBeInTheDocument();
    expect(screen.queryByText(T.BRIEFING_NO_IR, { exact: false })).not.toBeInTheDocument();
    expect(screen.getByText(T.BRIEFING_CHECKED)).toBeInTheDocument();
    // 근거 목록은 비어 있다 — claims 가 없으면 연결할 근거도 없다
    expect(evidence("Summary passage").querySelector("div")?.childElementCount).toBe(0);
    expect(within(reportSection("business")).queryByText(T.BUSINESS_ORIGINAL)).not.toBeInTheDocument();
    expect(within(reportSection("financials")).getByText(T.NO_FINANCIALS)).toBeInTheDocument();
  });

  it("prints a source's publication date when it has one", () => {
    const briefing = publicBriefingSchema.parse({
      status: "ready", report,
      claims: [{ claim_id: "claim-1", source_id: "source-1", statement: "A dated claim.", kind: "plan", entity: "Demo Company", period: null }],
      sources: [{ source_id: "source-1", url: "https://example.com/release", title: "Example release", published_at: "2026-01-01", collected_at: collected, entity: "Demo Company", kind: "official" }],
    });

    render(<PublicBriefing data={empty} symbol="DEMO" briefing={briefing} />);
    const claim = evidence("Summary passage");

    expect(within(claim).getByRole("link")).toHaveTextContent("Example release · 2026-01-01");
    expect(claim).toHaveTextContent(`${T.BRIEFING_KINDS.plan} · Demo Company`);
    expect(claim).not.toHaveTextContent("Demo Company ·");
  });
});

describe("NewsItem fallbacks", () => {
  it("offers reading questions only for topics it knows, and none without topics", () => {
    const verified = { date: "2026-01-05", title: "Verified headline", url: "https://example.com/rss", article_url: "https://example.com/article", content_status: "verified" as const, excerpt: "Checked excerpt" };

    const { container } = render(<ul><NewsItem item={verified} /><NewsItem item={{ ...verified, title: "Unknown topic headline", topics: ["unlisted-topic"] }} /><NewsItem item={{ ...verified, title: "Mixed topic headline", topics: ["unlisted-topic", "capital"] }} /></ul>);
    const items = [...container.querySelectorAll<HTMLLIElement>(":scope > ul > li")];

    expect(items).toHaveLength(3);

    expect(within(items[0]).queryByText(T.NEWS_READING)).not.toBeInTheDocument();
    expect(within(items[1]).queryByText(T.NEWS_READING)).not.toBeInTheDocument();
    expect(within(items[2]).getByText(T.NEWS_READING)).toBeInTheDocument();
    expect(within(items[2]).getByText(T.NEWS_TOPICS.capital)).toBeInTheDocument();
  });

  it("labels untitled articles with or without a safe link and says when the body was not checked", () => {
    render(<ul><NewsItem item={{ date: "2026-01-05", title: null, url: "https://example.com/untitled" }} /><NewsItem item={{ date: "2026-01-04", title: null, url: "javascript:alert(1)" }} /></ul>);
    expect(screen.getByRole("link", { name: T.NOT_PROVIDED })).toHaveAttribute("href", "https://example.com/untitled");
    expect(screen.getByText(T.NOT_PROVIDED, { selector: "p" })).toBeInTheDocument();
    expect(screen.getAllByText(T.NEWS_CONTENT_NOT_CHECKED)).toHaveLength(2);
    expect(screen.getAllByText(`2026-01-05 · ${T.NOT_PROVIDED}`)).toHaveLength(1);
  });
});
