import { z } from "zod";
import { fetchAPI } from "@/lib/api";

const number = z.number().nullable();

const allocation = z.object({ long: number, short: number, cash: number });

// 공식 지수 (#1676). 값이 없으면 백엔드가 null 을 보낸다 — 화면은 0 으로 바꾸지 않는다.
const marketIndex = z.object({
  key: z.string(), label: z.string(), close: number, prev_close: number, change_pct: number, date: z.string().nullable(),
  // 저장된 출처와 원천 심볼 (#1682)
  source: z.string().nullable().optional(), symbol: z.string().optional(),
});

// 경제 여건 점수 입력 지표별 저장 출처·기준일 (#1682)
const macroInput = z.object({ key: z.string(), date: z.string().nullable(), source: z.string().nullable() });

export const dashboardSchema = z.object({
  market_indices: z.array(marketIndex).optional(),
  macro_inputs: z.array(macroInput).optional(),
  exchange_rate: number.optional(),
  verdict: z.string(),
  verdict_level: z.string(),
  verdict_stale_inputs: z.array(z.object({ key: z.string(), label: z.string(), last_updated: z.string().nullable(), age_hours: number })).optional(),
  regime: z.object({ regime: z.string(), trend: z.string(), volatility: z.string().optional(), confidence: number, vix: number.optional(), fear_greed: number.optional() }),
  macro: z.object({ score: number, interpretation: z.string(), coverage: number.optional() }),
  actual_allocation: allocation.nullable().optional(),
  target_allocation: allocation.optional(),
  fx_unavailable: z.string().nullable().optional(),
  alerts: z.array(z.object({ level: z.string(), message: z.string() })),
});

const action = z.object({
  ticker: z.string(), name: z.string().nullable().optional(), action: z.string(),
  confidence: number, reasons: z.array(z.string()), account: z.string().optional(),
  position_pct: number.optional(), pnl_pct: number.optional(),
  alpha_action: z.string().nullable().optional(), portfolio_action: z.string().nullable().optional(),
  decision_id: number.optional(), as_of: z.string().nullable().optional(),
});

export const actionsSchema = z.object({
  urgent: z.array(action), check: z.array(action), hold: z.array(action), portfolio: z.array(action),
  generated_at: z.string().optional(),
});

// #1683: `system` 은 BUY 후보 emitter 의 분류(점수·임계는 API 값), `observations` 는 스캐너 관측이다.
const systemStance = z.object({ status: z.string(), score: number, threshold: number, reason: z.string().nullable() });

export const opportunitiesSchema = z.object({
  opportunities: z.array(z.object({
    change_1d: number.optional(), change_5d: number.optional(),
    ticker: z.string(), signal: z.string().nullable(), score: number,
    system: systemStance, observations: z.array(z.string()),
  })),
  generated_at: z.string().optional(),
});

export { pipelineSchema } from "./pipeline-contract";

export const freshnessSchema = z.object({
  pass: z.number(), warn: z.number(), fail: z.number(),
  details: z.array(z.object({ key: z.string(), label: z.string(), status: z.string(), message: z.string().optional(), last_updated: z.string().nullable().optional() })),
});

// 일부 API는 HTTP 200에서도 error 객체를 반환하므로 응답 구조까지 확인한다.
// 실패는 패널 하나의 "확인 불가" 로 접되, 이유(전송 vs 스키마 드리프트)는 서버 로그에 남긴다 (Codex #1658 P2).
export async function readPanel<T>(path: string, schema: z.ZodType<T>): Promise<T | null> {
  try {
    return schema.parse(await fetchAPI<unknown>(path));
  } catch (error) {
    const kind = error instanceof z.ZodError ? "schema" : "transport";

    console.warn(`[dashboard-next] ${path} unavailable (${kind}): ${error instanceof Error ? error.message.split("\n")[0] : String(error)}`);

    return null;
  }
}

export { displayNumber, displayTime } from "./format";

export type Actions = z.infer<typeof actionsSchema>;

export type Dashboard = z.infer<typeof dashboardSchema>;

export const portfolioSchema = z.object({
  holdings: z.array(z.object({ ticker: z.string(), name: z.string().nullable().optional(), account: z.string(), sector: z.string().nullable(), currency: z.string(), quantity: z.number(), latest_price: number, price_date: z.string().nullable() })),
  cash: z.object({ total_cash_usd: number, accounts: z.array(z.object({ account: z.string(), total_usd: number })) }),
});

export type Portfolio = z.infer<typeof portfolioSchema>;
