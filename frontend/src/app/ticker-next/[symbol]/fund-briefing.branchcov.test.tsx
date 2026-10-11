/**
 * ETF 브리핑 분기 잠금 — 운용 자료가 없거나, 지수 추종형(구성 미공개)이거나, 운용사 해설이 풍부한
 * 세 형태가 각자 다른 문장을 내야 한다. 픽스처는 실제 `researchSchema` 를 통과시킨다.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { FundBriefing } from "./fund-briefing";
import { researchSchema, type TickerReview } from "./data";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import { formatMoney, formatNum } from "@/lib/format";

afterEach(cleanup);

const SOURCE = "https://example.com/fund";

function fundData(fund: Record<string, unknown> | null, options: { description?: string; events?: Record<string, unknown>[]; priceHistory?: Record<string, unknown>[] } = {}): TickerReview {
  return {
    ticker: null, prices: null, history: null, actions: null, reviews: [],
    research: researchSchema.parse({
      ticker: "DEMO", news: [], events: options.events ?? [], fundamentals_history: [],
      dossier: {
        ticker: "DEMO", collected_at: "2026-01-06T09:00:00+09:00",
        profile: { name: "Demo Fund", symbol: "DEMO", quote_type: "ETF", description: options.description },
        statements: { income: [], cashflow: [], balance: [] },
        fund, price_history: options.priceHistory,
      },
    }),
  };
}

const DAILY = [
  { date: "2026-01-02", open: 10, high: 11, low: 9, close: 10, volume: 1_000 },
  { date: "2026-01-05", open: 10, high: 12, low: 10, close: 11, volume: 1_000 },
];

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

/** `<dl>` 의 용어 → 값. 같은 패널 안에서 라벨로 값을 찾는다. */
function terms(root: HTMLElement): Record<string, string> {
  return Object.fromEntries([...root.querySelectorAll("dt")].map(term => [term.textContent ?? "", term.nextElementSibling?.textContent ?? ""]));
}

describe("FundBriefing report — no fund data", () => {
  it("says the operating data is missing everywhere it would be used, and falls back for news, dates and events", () => {
    render(<FundBriefing data={fundData(null, { events: [{ date: "2026-02-01", event_type: "distribution", description: null }] })} />);
    expect(within(panel(T.FUND_INTRO)).getByText(T.FUND_DATA_MISSING)).toBeInTheDocument();
    expect(within(panel(T.POINTS)).getByText(T.FUND_DATA_MISSING)).toBeInTheDocument();
    expect(within(reportSection("summary")).getByText(T.FUND_DATA_MISSING)).toBeInTheDocument();
    expect(within(panel(T.RISK_FACTS)).getByText(T.NO_RISK_FACT)).toBeInTheDocument();
    expect(within(panel(T.RISK_FACTS)).queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText(`${T.SOURCE} · ${T.NOT_PROVIDED}`)).toBeInTheDocument();
    expect(within(panel(T.FUND_INTRO)).getByText(`${T.FUND_DETAILS_DATE} · ${T.UNKNOWN_DATE}`)).toBeInTheDocument();
    expect(terms(panel(T.FUND_INTRO))).toEqual({ [T.AUM]: "—", [T.EXPENSE]: "—", [T.INCEPTION]: "—", [T.HOLDING_COUNT]: "—" });
    expect(within(reportSection("changes")).getByText(T.NEWS_NOT_CHECKED)).toBeInTheDocument();
    expect(within(reportSection("schedule")).getByText(`2026-02-01 · ${T.NOT_PROVIDED}`)).toBeInTheDocument();
  });
});

describe("FundBriefing report — symbol default", () => {
  const yahoo = `${T.SOURCE} · ${T.YAHOO}`;

  it("takes the research ticker when no symbol is passed, so the collected price history links to that ticker", () => {
    render(<FundBriefing data={fundData(null, { priceHistory: DAILY })} />);
    expect(within(reportSection("judgment")).getByRole("link", { name: yahoo })).toHaveAttribute("href", "https://finance.yahoo.com/quote/DEMO/history/");
  });

  it("still renders without research or a symbol: stored prices, the stored-price note and no Yahoo link", () => {
    render(<FundBriefing data={{ ticker: null, prices: { prices: DAILY }, history: null, actions: null, reviews: [], research: null }} />);
    const prices = panel(T.PRICE_RANGE);

    expect(terms(prices)).toMatchObject({ [T.RANGE_HIGH]: formatMoney(12), [T.RANGE_LOW]: formatMoney(9) });
    expect(within(prices).getByText(T.STORED_PRICE_SOURCE)).toBeInTheDocument();
    expect(within(prices).queryByRole("link", { name: yahoo })).not.toBeInTheDocument();
    expect(within(reportSection("summary")).getByText(T.FUND_DATA_MISSING)).toBeInTheDocument();
    expect(within(reportSection("schedule")).getByText(T.DOCUMENT_NO_SCHEDULE)).toBeInTheDocument();
  });
});

describe("FundBriefing report — index-tracking fund without published holdings", () => {
  const indexFund = {
    source_name: "Example Issuer", source_url: SOURCE, prospectus_url: "https://example.com/prospectus",
    benchmark: "Demo Composite Index", issuer: null, expense_pct: null, nav: 10_000, currency: "KRW", deviation_pct: null,
    holdings: [], risks: [{ title: "Unlisted Risk", text: "Issuer wording for a risk the glossary does not cover." }],
    structure_notes: ["Synthetic replication through swaps."],
  };

  it("explains the benchmark instead of a concentration it cannot see, and keeps unknown risks out of the glossary", () => {
    render(<FundBriefing data={fundData(indexFund)} symbol="DEMO" />);
    expect(terms(panel(T.FUND_INTRO))).toEqual({ [T.ISSUER]: "—", [T.EXPENSE]: "—", [T.BENCHMARK]: "Demo Composite Index", [T.NAV]: "10,000 KRW" });
    const points = panel(T.POINTS);

    expect(within(points).getByText(T.FUND_BENCHMARK("Demo Composite Index"))).toBeInTheDocument();
    expect(within(points).getByText(T.FUND_HOLDINGS_UNAVAILABLE)).toBeInTheDocument();
    expect(within(points).queryByText(T.EXPENSE)).not.toBeInTheDocument();
    const risks = panel(T.RISK_FACTS);

    expect(within(risks).getByRole("heading", { name: T.FUND_STRUCTURE })).toBeInTheDocument();
    expect(within(risks).getByText("Synthetic replication through swaps.")).toBeInTheDocument();
    // 용어집에 없는 위험은 지어낸 해설로 바꾸지 않는다 — 원문도, "확정하기 어렵다" 문구도 내지 않는다
    expect(within(risks).queryByText(T.RISK_ORIGINAL)).not.toBeInTheDocument();
    expect(within(risks).queryByText(T.NO_RISK_FACT)).not.toBeInTheDocument();
    expect(within(risks).getByRole("link", { name: T.FUND_SOURCE })).toHaveAttribute("href", SOURCE);
    expect(within(risks).getByRole("link", { name: T.PROSPECTUS })).toHaveAttribute("href", "https://example.com/prospectus");
    const valuation = panel(T.VALUATION);

    expect(terms(valuation)).toEqual({ [T.NAV]: "10,000 KRW", [T.DEVIATION]: "—" });
    expect(within(valuation).getByText(T.FUND_SNAPSHOT_NOTE)).toBeInTheDocument();
  });

  it("shows the issuer, total expense and the provider's deviation when they are published", () => {
    render(<FundBriefing data={fundData({ ...indexFund, issuer: "Example Asset Management", expense_pct: 0.45, deviation_pct: 0.12 })} symbol="DEMO" />);
    expect(terms(panel(T.FUND_INTRO))).toMatchObject({ [T.ISSUER]: "Example Asset Management", [T.EXPENSE]: `${formatNum(0.45, 2)}%` });
    expect(terms(panel(T.VALUATION))).toMatchObject({ [T.DEVIATION]: `${formatNum(0.12, 2)}%` });
    expect(within(panel(T.POINTS)).getByText(T.FUND_COST_EXPLAIN)).toBeInTheDocument();
  });
});

describe("FundBriefing report — issuer-documented fund", () => {
  const documented = {
    source_name: "Example Issuer", source_url: SOURCE, strategy_text: "Tracks listed space-economy companies.",
    details_as_of: "2026-01-04", holdings_as_of: "2026-01-05", aum: 5_000_000_000, currency: "USD", expense_pct: 0.75, inception: "2021-01-01", holding_count: 40,
    holdings: [{ name: "Sample Launch Co", weight_pct: 9 }, { name: "Sample Orbit Co", weight_pct: 7 }, { name: "Sample Ground Co", weight_pct: 5 }, { name: "Sample Tail Co", weight_pct: 1 }],
    risks: [{ title: "Sector Focus Risk", text: "Issuer text about sector focus." }, { title: "Unlisted Risk", text: "Issuer text without a glossary entry." }],
    highlights: [
      { name: "Sample Launch Co", symbol: "LNCH", description: "Builds launch vehicles.", explanation: "Largest disclosed launch provider." },
      { name: "Sample Orbit Co", symbol: "ORBT", description: "Operates satellites.", explanation: null },
    ],
    exposure_text: "Holds operating companies, not futures.", faq_as_of: null, source_consistency_issue: true,
    faq: [{ question: "Does the fund hold private companies?", answer: "Only through listed vehicles." }],
  };

  it("summarises concentration, cost, highlighted businesses, structure and sources from the issuer's own data", () => {
    render(<FundBriefing data={fundData(documented, { description: "Provider description of the fund." })} symbol="DEMO" />);
    const intro = panel(T.FUND_INTRO);

    expect(terms(intro)).toEqual({ [T.AUM]: "50억 USD", [T.EXPENSE]: `${formatNum(0.75, 2)}%`, [T.INCEPTION]: "2021-01-01", [T.HOLDING_COUNT]: "40" });
    expect(within(intro).getByText("50억 USD")).toHaveAttribute("title", "5,000,000,000 USD");
    expect(within(intro).getByText(T.BUSINESS_ORIGINAL)).toBeInTheDocument();
    expect(within(intro).getByRole("link", { name: `${T.SOURCE} · Example Issuer` })).toHaveAttribute("href", SOURCE);
    const points = panel(T.POINTS);

    expect(within(points).getByText(T.FUND_CONCENTRATION(3, formatNum(21, 2)))).toBeInTheDocument();
    expect(within(points).getByText(`${T.HOLDINGS_DATE} · 2026-01-05`)).toBeInTheDocument();
    expect(within(points).queryByText("Sample Tail Co")).not.toBeInTheDocument();
    const launch = within(points).getByRole("heading", { name: /Sample Launch Co/ }).closest("article");
    const orbit = within(points).getByRole("heading", { name: /Sample Orbit Co/ }).closest("article");

    if (!launch || !orbit) throw new Error("highlight articles missing");
    expect(within(launch).getByText("Largest disclosed launch provider.")).toBeInTheDocument();
    expect([...orbit.children].map(child => child.tagName)).toEqual(["H4", "DETAILS"]);
    expect(within(points).getByText("Holds operating companies, not futures.")).toBeInTheDocument();
    expect(within(points).getByText(`${T.FAQ_DATE} · ${T.UNKNOWN_DATE}`)).toBeInTheDocument();
    expect(within(points).getByText(T.SOURCE_CONSISTENCY)).toBeInTheDocument();
    expect(within(points).getByText("Does the fund hold private companies?")).toBeInTheDocument();
    const risks = panel(T.RISK_FACTS);

    expect(within(risks).getByRole("heading", { name: T.RISK_GLOSSARY["Sector Focus Risk"].title })).toBeInTheDocument();
    expect(within(risks).getByText("Issuer text about sector focus.")).toBeInTheDocument();
    expect(within(risks).queryByText("Issuer text without a glossary entry.")).not.toBeInTheDocument();
    expect(within(risks).getByRole("link", { name: T.OFFICIAL })).toHaveAttribute("href", SOURCE);
    expect(within(reportSection("summary")).getByText("Tracks listed space-economy companies.")).toBeInTheDocument();
    expect(screen.getByText(`${T.SOURCE} · Example Issuer`, { selector: "p" })).toBeInTheDocument();
  });

  it("prints the compact asset size without a currency, and an unknown holdings date, when neither is published", () => {
    render(<FundBriefing data={fundData({ ...documented, currency: null, holdings_as_of: null })} symbol="DEMO" />);
    expect(terms(panel(T.FUND_INTRO))[T.AUM]).toBe("50억");
    expect(within(panel(T.POINTS)).getByText(`${T.HOLDINGS_DATE} · ${T.UNKNOWN_DATE}`)).toBeInTheDocument();
  });
});

describe("FundBriefing details — holdings table", () => {
  it("lists every published holding with the total and the holdings date", () => {
    render(<FundBriefing details data={fundData({ source_name: "Example Issuer", source_url: SOURCE, holdings_as_of: "2026-01-05", holdings: [{ name: "Sample Launch Co", weight_pct: 9.5 }, { name: "Sample Orbit Co", weight_pct: 7.25 }], risks: [] })} />);
    const holdings = panel(T.HOLDINGS);

    expect(within(holdings).getAllByRole("row").slice(1).map(row => row.textContent)).toEqual([`Sample Launch Co${formatNum(9.5, 2)}%`, `Sample Orbit Co${formatNum(7.25, 2)}%`]);
    expect(within(holdings).getByText(T.FUND_TOTAL(2, formatNum(16.75, 2)))).toBeInTheDocument();
    expect(within(holdings).queryByText(T.FUND_UNKNOWN_DATE)).not.toBeInTheDocument();
    expect(within(holdings).getByRole("link")).toHaveAttribute("href", `${SOURCE}#holdings`);
    expect(screen.getByText(`${T.HOLDINGS_DATE} · 2026-01-05`)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: T.VALUATION })).toBeInTheDocument();
  });

  it("says there is no holdings data and no holdings date instead of borrowing the collection date", () => {
    render(<FundBriefing details data={fundData(null)} />);
    const holdings = panel(T.HOLDINGS);

    expect(within(holdings).getByText(T.NO_DATA)).toBeInTheDocument();
    expect(within(holdings).getByText(T.FUND_UNKNOWN_DATE)).toBeInTheDocument();
    expect(within(holdings).queryByText(T.FUND_TOTAL(0, formatNum(0, 2)))).not.toBeInTheDocument();
    expect(within(holdings).queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText(`${T.HOLDINGS_DATE} · ${T.UNKNOWN_DATE}`)).toBeInTheDocument();
  });
});
