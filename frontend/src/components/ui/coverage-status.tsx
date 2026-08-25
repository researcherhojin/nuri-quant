/**
 * CoverageStatus — Universe + Agent 데이터 coverage 표시 위젯 (#272 Phase 4).
 *
 * Backend `/api/coverage` 응답을 테이블로 렌더. US-only 테이블의 KR 컬럼은
 * `n/a (US-only)` 로 표시 (#288 컨벤션).
 *
 * PASS=emerald, FAIL=red. 모든 체크 PASS 시 헤더 "5/5 PASS" 녹색.
 *
 * U2b-3 (#1210): 기본은 한 줄 요약으로 접힘 — native <details> 라 client JS 없이
 * server component 유지. 운영자 워크플로에서 coverage 는 예외 시에만 보는 정보.
 */

export interface CoverageCheck {
  name: string;
  actual: number;
  threshold: number;
  status: "PASS" | "FAIL";
  detail: string;
  us_only: boolean;
}

export interface CoverageData {
  pass: number;
  fail: number;
  exit_code: 0 | 1;
  checks: CoverageCheck[];
  error?: string;
}

function displayName(name: string): string {
  // "data.analyst_ratings" → "analyst_ratings"
  return name.replace(/^data\./, "");
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function krColumnText(c: CoverageCheck): string {
  if (c.us_only) return "n/a (US-only)";
  // For non-US-only, the detail already includes the ticker count;
  // extract just the first "X/Y" fragment if present, else show detail.
  const match = c.detail.match(/(\d+\/\d+)/);
  return match ? match[1] : c.detail;
}

export function CoverageStatus({ data }: { data: CoverageData }) {
  if (data.error) {
    return (
      <div className="rounded-md border border-red-500/20 bg-red-500/10 p-3 text-sm text-red-400">
        Coverage 확인 실패: {data.error}
      </div>
    );
  }

  const allPass = data.fail === 0;
  const total = data.checks.length;
  const headerColor = allPass ? "text-emerald-400" : "text-red-400";
  // FINDING-002 (design-review): 이모지 → intent-색 글리프 (headerColor 가 색을 이미 나른다)
  const headerIcon = allPass ? "\u2713" : "\u2715";

  return (
    <details className="rounded-md border border-border bg-card/40 p-3 group" data-testid="coverage-details">
      <summary className="flex items-center justify-between cursor-pointer list-none [&::-webkit-details-marker]:hidden">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          <span className="inline-block mr-1.5 text-muted-foreground/60 transition-transform group-open:rotate-90">&#9656;</span>
          Data Coverage
        </span>
        <span className={`text-sm font-medium ${headerColor}`}>
          {headerIcon} {data.pass}/{total} PASS
        </span>
      </summary>

      <table className="w-full text-[12px] mt-2">
        <thead className="text-left text-muted-foreground/70">
          <tr className="border-b border-border/50">
            <th className="py-1 font-normal">Table</th>
            <th className="py-1 text-right font-normal">US</th>
            <th className="py-1 text-right font-normal">KR</th>
            <th className="py-1 text-right font-normal">Threshold</th>
            <th className="py-1 text-right font-normal">Status</th>
          </tr>
        </thead>
        <tbody>
          {data.checks.map((c) => {
            const statusStyle = c.status === "PASS" ? "text-emerald-400" : "text-red-400";
            const krStyle = c.us_only ? "text-muted-foreground/60 italic" : "text-foreground";
            return (
              <tr key={c.name} className="border-b border-border/30 last:border-0">
                <td className="py-1 font-mono">{displayName(c.name)}</td>
                <td className="py-1 text-right font-mono">{formatPercent(c.actual)}</td>
                <td className={`py-1 text-right font-mono ${krStyle}`}>{krColumnText(c)}</td>
                <td className="py-1 text-right font-mono text-muted-foreground/70">
                  &ge;{formatPercent(c.threshold)}
                </td>
                <td className={`py-1 text-right font-medium ${statusStyle}`}>
                  {c.status}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {data.checks.some((c) => c.us_only) && (
        <p className="mt-2 text-[10px] text-muted-foreground/60">
          KR &quot;n/a (US-only)&quot;: yfinance .KS / SEC EDGAR 소스가 KR 종목 미지원 (수집 실패 아님).
        </p>
      )}
    </details>
  );
}
