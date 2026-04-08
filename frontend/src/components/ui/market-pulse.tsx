/**
 * MarketPulse — 시장 awareness 카드 6개 (Card 한 개 안에 grid).
 *
 * 데이터 소스: /api/dashboard 응답의 regime + macro 필드만 사용 (새 API 호출 0).
 * 실시간 차트 X — 숫자/sparkline 카드만. TradingView를 다시 만드는 게 아니라,
 * "decision support" 컨텍스트로 시장 상태를 한눈에 보여주는 게 목적.
 *
 * 색상 의미 (decision-driven, not aesthetic):
 *   - 우호 (greed/bull/macro high) → emerald
 *   - 경계 (extreme greed/extreme fear/bear/macro low) → red
 *   - 중립 → muted
 */
import { Card, CardContent } from "@/components/ui/card";
import { Metric } from "@/components/ui/metric";

interface MarketPulseProps {
  regime: {
    regime: string;
    trend: string;
    volatility?: string;
    confidence: number;
    vix?: number | null;
    fear_greed?: number | null;
  };
  macro: {
    score: number;
    interpretation: string;
  };
}

/** VIX color: <15 calm (emerald), 15-25 normal, >25 elevated (red). */
function vixColor(vix: number | null | undefined): "green" | "red" | "default" {
  if (vix == null) return "default";
  if (vix < 15) return "green";
  if (vix > 25) return "red";
  return "default";
}

/** Fear & Greed color: <25 fear (red, contrarian buy), >75 greed (red, caution), middle = green. */
function fearGreedColor(fg: number | null | undefined): "green" | "red" | "default" {
  if (fg == null) return "default";
  if (fg < 25 || fg > 75) return "red";
  if (fg >= 40 && fg <= 60) return "green";
  return "default";
}

/** Fear & Greed label. */
function fearGreedLabel(fg: number | null | undefined): string {
  if (fg == null) return "—";
  if (fg < 25) return "Extreme Fear";
  if (fg < 45) return "Fear";
  if (fg <= 55) return "Neutral";
  if (fg <= 75) return "Greed";
  return "Extreme Greed";
}

/** Macro score color: 60+ favorable, <40 weak, middle neutral. */
function macroColor(score: number): "green" | "red" | "default" {
  if (score >= 60) return "green";
  if (score < 40) return "red";
  return "default";
}

/** Trend color: bull=green, bear=red, sideways=default. */
function trendColor(trend: string): "green" | "red" | "default" {
  if (trend === "bull") return "green";
  if (trend === "bear") return "red";
  return "default";
}

/** Regime confidence interpretation. */
function confidenceLabel(conf: number): string {
  if (conf >= 80) return "high conviction";
  if (conf >= 60) return "moderate";
  return "low conviction";
}

export function MarketPulse({ regime, macro }: MarketPulseProps) {
  const vix = regime.vix ?? null;
  const fg = regime.fear_greed ?? null;
  const trend = regime.trend || "unknown";
  const vol = regime.volatility || "unknown";

  return (
    <Card className="bg-card border-border">
      <CardContent className="pt-4 pb-3">
        <div className="flex items-center justify-between mb-3">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider">
            Market Pulse
          </p>
          <span className="text-[10px] text-muted-foreground/50">
            {regime.regime}
          </span>
        </div>
        <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
          <Metric
            label="Trend"
            value={trend.toUpperCase()}
            sub={vol}
            color={trendColor(trend)}
          />
          <Metric
            label="VIX"
            value={vix?.toFixed(1) ?? "—"}
            sub={vix == null ? "no data" : vix < 15 ? "calm" : vix > 25 ? "elevated" : "normal"}
            color={vixColor(vix)}
          />
          <Metric
            label="Fear & Greed"
            value={fg ?? "—"}
            sub={fearGreedLabel(fg)}
            color={fearGreedColor(fg)}
          />
          <Metric
            label="Macro"
            value={`${macro.score}/100`}
            sub={macro.interpretation}
            color={macroColor(macro.score)}
          />
          <Metric
            label="Confidence"
            value={`${regime.confidence}%`}
            sub={confidenceLabel(regime.confidence)}
            color="default"
          />
          <Metric
            label="Volatility"
            value={vol.replace("_vol", "").toUpperCase()}
            sub={vol === "high_vol" ? "elevated" : vol === "low_vol" ? "calm" : "normal"}
            color={vol === "high_vol" ? "red" : vol === "low_vol" ? "green" : "default"}
          />
        </div>
      </CardContent>
    </Card>
  );
}
