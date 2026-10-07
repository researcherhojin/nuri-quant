import { z } from "zod";
import { publicBriefingSchema } from "./public-briefing-schema";
import { API_BASE, fetchAPI } from "@/lib/api";
import { actionsSchema } from "@/app/(overview)/data";
import { ScoringDetailSchema } from "@/app/decisions/verdict-path";

const num = z.number().nullish();

const text = z.string().nullish();

const verdict = z.object({
  agent_name: z.string(), action: text, confidence: num, reasoning: text,
  degraded: z.boolean().optional(), abstained: z.boolean().optional(),
  data_points: z.object({ debt_pct: num, position_basis: text }).nullish().catch(null),
});

export const tickerSchema = z.object({
  ticker: z.string(), name: text,
  price: z.object({ close: num, date: text }).nullish(),
  consensus: z.object({
    final_action: text, final_confidence: num, agreement_rate: num, as_of: text,
    verdicts: z.array(verdict).optional(), dissent: z.array(z.string()).optional(), error: text,
    scoring_detail: ScoringDetailSchema.nullish().catch(null),
  }).nullish(),
  fundamentals: z.object({ date: text, market_cap: num, forward_pe: num, price_to_book: num, operating_margin: num, earnings_growth: num, current_ratio: num, dividend_yield: num, pe_ratio: num, roe: num, revenue_growth: num, debt_to_equity: num, profit_margin: num, beta: num }).nullish(),
  analyst_ratings: z.array(z.object({ firm: z.string(), date: text, to_grade: text, action: text, target_price: num })).optional(),
  earnings: z.array(z.object({ quarter: text, eps_actual: num, eps_estimate: num, surprise_pct: num })).optional(),
  insider_trades: z.array(z.object({ date: text, insider_name: text, transaction_type: text, shares: num })).optional(),
  superinvestors: z.array(z.object({ investor: z.string(), portfolio_pct: num, filing_date: text })).optional(),
});

export const pricesSchema = z.object({ prices: z.array(z.object({
  date: z.string(), open: z.number(), high: z.number(), low: z.number(), close: z.number(), volume: z.number(),
})) });

export const historySchema = z.object({ decisions: z.array(z.object({
  id: z.number().int().positive(), ticker: z.string(), date: z.string(), action: z.string(),
  confidence: num, reasoning: text, outcome: text, pnl_7d: num, pnl_30d: num,
})) });

// 정상 응답은 생성 시각을 포함한다. 실패 시 API의 빈 버킷 fallback을 정상적인 빈 목록으로 읽지 않는다.
const reviewSchema = actionsSchema.extend({ generated_at: z.string() });

const financialPeriod = z.object({ period: z.string(), revenue: num, operating_income: num, net_income: num, operating_cashflow: num, free_cashflow: num, cash: num, debt: num });

const newsItem = z.object({ date: z.string(), title: text, url: text, source: text, article_url: text, excerpt: text, content_checked_at: text, content_status: z.enum(["verified", "unavailable", "not_checked"]).optional(), topics: z.array(z.string()).optional() });

const fundSchema = z.object({
  source_name: z.string(), source_url: z.string(), details_as_of: text, holdings_as_of: text,
  name: text, description: text, strategy_text: text, inception: text, expense_pct: num, aum: num, currency: text, holding_count: num,
  prospectus_url: text, valuation_as_of: text, pe: num, pb: num, ps: num,
  holdings: z.array(z.object({ name: z.string(), weight_pct: z.number().min(0).max(100) })),
  risks: z.array(z.object({ title: z.string(), text: z.string() })),
  highlights: z.array(z.object({ name: z.string(), symbol: z.string(), description: z.string(), explanation: text })).optional(),
  faq: z.array(z.object({ question: z.string(), answer: z.string() })).optional(), faq_as_of: text,
  exposure_text: text, source_consistency_issue: z.boolean().optional(),
  benchmark: text, issuer: text, nav: num, deviation_pct: num, structure_notes: z.array(z.string()).optional(),
});

export const researchSchema = z.object({
  ticker: z.string(),
  public_briefing: publicBriefingSchema.nullish().catch(null),
  today: text, collected_today: z.boolean().optional(),
  dossier: z.object({
    ticker: z.string(), collected_at: z.string(), unavailable: z.array(z.string()).optional(),
    profile: z.object({ name: z.string(), display_name: text, identity_source_url: text, symbol: z.string(), description: text, sector: text, industry: text, country: text, website: text, exchange: text, quote_type: text, currency: text, financial_currency: text, market_cap: num }),
    business: z.object({ summary: text, sector_label: text, industry_label: text, has_financing: z.boolean(), source_name: z.string(), source_url: z.string(), activities: z.array(z.object({ title: z.string(), explanation: z.string(), checkpoint: z.string(), source_phrase: z.string() })) }).nullish(),
    statements: z.object({ income: z.array(financialPeriod), cashflow: z.array(financialPeriod), balance: z.array(financialPeriod) }),
    fund: fundSchema.nullish(), price_history: pricesSchema.shape.prices.optional(), news: z.array(newsItem).optional(),
    news_check: z.object({ checked_at: z.string(), window_start: z.string(), window_end: z.string(), sources: z.array(z.string()), failed_sources: z.array(z.string()) }).optional(),
  }).nullable(),
  news: z.array(newsItem),
  events: z.array(z.object({ date: z.string(), event_type: text, description: text })),
  fundamentals_history: z.array(z.object({ date: z.string(), pe_ratio: num, forward_pe: num, price_to_book: num })),
});

async function readResearch(symbol: string) {
  try {
    // 명시적 수집 직후 브리핑을 다시 읽을 때 이전 캐시를 보여주지 않는다.
    const response = await fetch(`${API_BASE}/api/ticker/${encodeURIComponent(symbol)}/research`, { cache: "no-store" });

    if (!response.ok) return null;

    const research = researchSchema.parse(await response.json());

    if (research.ticker !== symbol || (research.dossier && (research.dossier.ticker !== symbol || research.dossier.profile.symbol !== symbol))) return null;

    return research;
  } catch {
    return null;
  }
}

async function read<T>(path: string, schema: z.ZodType<T>): Promise<T | null> {
  try {
    return schema.parse(await fetchAPI<unknown>(path));
  } catch {
    console.warn(`[ticker-preview] unavailable: ${path}`);

    return null;
  }
}

export async function loadTicker(symbol: string) {
  const encoded = encodeURIComponent(symbol);

  const [ticker, prices, history, actions, research] = await Promise.all([
    read(`/api/ticker/${encoded}?stored_only=true`, tickerSchema),
    read(`/api/ticker/${encoded}/prices?days=365`, pricesSchema),
    read(`/api/decisions?ticker=${encoded}&limit=12`, historySchema),
    read("/api/actions", reviewSchema),
    readResearch(symbol),
  ]);

  // 포트폴리오 규칙과 기대수익 판단은 독립적인 축으로 유지한다.
  const reviews = actions ? (["urgent", "check", "portfolio", "hold"] as const).flatMap(bucket =>
    actions[bucket].flatMap(item => item.ticker === symbol ? [{ ...item, bucket }] : [])) : [];

  return { ticker, prices, history, actions, reviews, research };
}

export type Ticker = z.infer<typeof tickerSchema>;

export type TickerReview = Awaited<ReturnType<typeof loadTicker>>;
