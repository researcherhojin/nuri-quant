import Link from "next/link";
import { ArrowUpRight, ArrowLeftRight, RefreshCw, Activity, Globe2, ShieldCheck, ChartNoAxesCombined, Layers3, ListFilter, Radar } from "lucide-react";
import { DASHBOARD_NEXT as COPY } from "@/lib/strings";
import { actionsSchema, dashboardSchema, displayNumber, displayTime, freshnessSchema, opportunitiesSchema, pipelineSchema, portfolioSchema, readPanel } from "./data";
import { displayChange } from "./format";
import { Inbox, type Bucket } from "./inbox";
import { PortfolioPanel } from "./portfolio-panel";
import { RefreshDialog } from "./refresh-dialog";
import { PipelineStatus } from "./pipeline-status";
import { DetailDialog } from "./detail-dialog";
import styles from "./dashboard.module.css";

export const dynamic = "force-dynamic";
export const metadata = { title: "Overview · Nuri-Quant" };
const buckets: Bucket[] = ["urgent", "check", "portfolio", "hold"];
const statusLabels: Record<string, string> = { done: "완료", success: "완료", running: "실행 중", error: "오류", idle: "대기", PASS: "정상", WARN: "주의", FAIL: "지연" };
const regimeLabels: Record<string, string> = { bull_low_vol: "상승 · 저변동", bull_high_vol: "상승 · 고변동", bear_low_vol: "하락 · 저변동", bear_high_vol: "하락 · 고변동", sideways_low_vol: "횡보 · 저변동", sideways_high_vol: "횡보 · 고변동" };

function Empty({ failed = false }: { failed?: boolean }) {
  return <p className={styles.empty}>{failed ? COPY.UNAVAILABLE : COPY.EMPTY}</p>;
}

export default async function DashboardNext({ searchParams }: { searchParams?: Promise<{ bucket?: string }> }) {
  const params = await searchParams;
  const bucket = buckets.find((value) => value === params?.bucket) ?? "urgent";
  const [dashboard, actions, opportunities, pipeline, freshness, portfolio] = await Promise.all([
    readPanel("/api/dashboard", dashboardSchema),
    readPanel("/api/actions", actionsSchema),
    readPanel("/api/opportunities", opportunitiesSchema),
    readPanel("/api/pipeline/status", pipelineSchema),
    readPanel("/api/freshness", freshnessSchema),
    readPanel("/api/portfolio", portfolioSchema),
  ]);
  const missing = [dashboard, actions, opportunities, pipeline, freshness, portfolio].filter((value) => value === null).length;
  const macroAvailable = dashboard && dashboard.macro.coverage !== 0 && dashboard.macro.interpretation !== "Unavailable";
  const regimeAvailable = dashboard && dashboard.regime.regime !== "unknown";
  const delayed = freshness?.details.filter((item) => item.status !== "PASS").sort((a, b) => Number(b.status === "FAIL") - Number(a.status === "FAIL")) ?? [];
  const reliability = !freshness?.details.length ? "신선도 확인 불가" : freshness.fail > 0 ? `지연된 데이터 ${freshness.fail}개` : freshness.warn > 0 ? `주의할 데이터 ${freshness.warn}개` : "수집 데이터 정상";
  const restricted = dashboard?.verdict_level === "stale";

  return (
    <div className={styles.dashboard} data-testid="overview-dashboard">
      <header className={styles.header}>
        <div className={styles.titleGroup}><h1>{COPY.TITLE}</h1><span className={styles.preview}>PREVIEW</span><p>시장과 포트폴리오의 현재 상태</p></div>
        <div className={styles.headerActions}>
          <Link href="/" prefetch={false} className={styles.button}><ArrowLeftRight size={14} />{COPY.COMPARE}</Link>
          <a href="/dashboard-next" className={styles.iconButton} aria-label={COPY.REFRESH}><RefreshCw size={15} /></a>
        </div>
      </header>

      <section className={styles.summary} aria-label="오늘의 확인 순서">
        <div className={styles.verdict}><span className={styles.statusDot} data-tone={restricted ? "warning" : "neutral"} /><span className={styles.summaryLabel}>시스템 의견</span><p>{dashboard?.verdict || COPY.UNAVAILABLE}</p></div>
        <a href="#trust" className={styles.reliability} data-health={freshness?.details.length && !delayed.length ? "ready" : "attention"}><ShieldCheck size={14} />{reliability}</a>
        {missing > 0 && <p role="status" className={styles.warning}>일부 정보를 불러오지 못했습니다 ({missing}/6). {COPY.UNAVAILABLE}</p>}
      </section>

      <div className={styles.metrics} aria-label="현재 시장 환경">
        <article><div className={styles.metricLabel}><DetailDialog label="시장 흐름 ⓘ" title="시장 흐름을 읽는 법"><p>시스템이 분류한 시장의 추세와 변동성입니다. 상승·하락·횡보는 추세, 저변동·고변동은 가격 흔들림의 정도를 뜻합니다.</p><p>분류 신뢰도는 모델의 분류 점수이며 앞으로 오를 확률이나 수익 확률이 아닙니다. 데이터 업데이트 상태와 함께 확인하세요.</p></DetailDialog><Globe2 size={16} /></div><strong className={styles.regimeValue}>{regimeAvailable ? regimeLabels[dashboard.regime.regime] || dashboard.regime.regime : "—"}</strong><small>분류 신뢰도 {displayNumber(regimeAvailable ? dashboard.regime.confidence : null, "%")}</small></article>
        <article><div className={styles.metricLabel}><DetailDialog label="경제 여건 점수 ⓘ" title="경제 여건 점수의 의미"><p>금리·수익률 곡선·고용·물가·시장 심리·경제 이벤트 등을 종합한 시스템 점수입니다. 높을수록 투자 환경에 우호적인 것으로 해석합니다.</p><p>경제 성장률이나 수익 확률이 아닙니다. 입력이 부족하면 제공된 지표만으로 계산되므로 데이터 상태를 함께 확인해야 합니다.</p></DetailDialog><ChartNoAxesCombined size={16} /></div><strong>{displayNumber(macroAvailable ? dashboard.macro.score : null)}<span> / 100</span></strong><small>{macroAvailable ? ({ Favorable: "우호적", Neutral: "중립", Cautious: "주의", Adverse: "비우호적", Insufficient: "입력 부족" }[dashboard.macro.interpretation] || dashboard.macro.interpretation) : "경제 지표 확인 필요"}</small></article>
        <article><div className={styles.metricLabel}><span>변동성 지수</span><Activity size={16} /></div><strong>{displayNumber(dashboard?.regime.vix)}</strong><small>VIX · 최근 관측값</small></article>
        <article><div className={styles.metricLabel}><span>우선 점검 항목</span><span className={styles.metricTag}>SYSTEM</span></div><strong>{actions ? actions.urgent.length : "—"}<span> 우선 확인</span></strong><small>검토 {actions ? actions.check.length : "—"} · 포트폴리오 규칙 {actions ? actions.portfolio.length : "—"}</small></article>
      </div>

      <div className={styles.primaryGrid}>
        <section id="review" className={`${styles.panel} ${styles.reviewPanel}`}>
          <div className={styles.panelHeading}><h2><ListFilter size={14} />{COPY.INBOX}</h2><div className={styles.pipelineControls}><DetailDialog label="읽는 법 ⓘ" title="보유 종목 점검을 읽는 법"><p>현재 보유 종목에 대해 백엔드가 생성한 점검 목록입니다. 종목을 선택하면 판정 기준일, 근거, 보유 비중과 두 종류의 신호를 확인할 수 있습니다.</p><ul><li>우선 확인: 시스템이 우선 점검 대상으로 분류한 항목입니다. 표시된 위험 근거를 먼저 확인하세요.</li><li>검토: 추가 확인이 필요한 시스템 판단입니다.</li><li>포트폴리오 규칙: 집중도·업종·레버리지 등 보유 구성의 점검입니다.</li><li>유지: 시스템이 유지로 분류한 항목입니다.</li></ul><p>기대수익 신호(LONG·SHORT·FLAT)와 포트폴리오 신호(REBALANCE·TRIM·HEDGE·NONE)는 서로 다른 축입니다. 포트폴리오 규칙을 매도 판단으로 해석하지 마세요.</p><p>시스템 신뢰도는 수익 확률이 아닙니다. 목록 생성 시각과 판정 기준일도 다릅니다. 오래된 입력이나 연결된 원장이 없는 항목은 근거를 추가 확인하세요.</p></DetailDialog><Link href="/decisions" className={styles.textLink}>판정 원장 <ArrowUpRight size={14} /></Link></div></div>
          <Inbox key={bucket} actions={actions} initialBucket={bucket} />
        </section>
        <section className={styles.panel} aria-label="포트폴리오 구성">
          <div className={styles.panelHeading}><h2><Layers3 size={14} />{COPY.ALLOCATION}</h2><Link href="/portfolio" className={styles.textLink}>전체 보기 <ArrowUpRight size={14} /></Link></div>
          <PortfolioPanel portfolio={portfolio} exchangeRate={dashboard?.exchange_rate} />
          <Link href="/dashboard-next?bucket=portfolio" prefetch={false} className={styles.ruleLink}><span>포트폴리오 규칙 <b>{actions ? actions.portfolio.length : "—"}건</b></span><ArrowUpRight size={15} /></Link>
        </section>
      </div>

      <div className={styles.secondaryGrid}>
        <section className={styles.panel} aria-label="시장 탐색 후보">
          <div className={styles.panelHeading}><h2><Radar size={14} />{COPY.RADAR}</h2><Link href="/scan" className={styles.textLink}>스캐너 <ArrowUpRight size={14} /></Link></div>
          <div className={styles.panelBody}>
            {opportunities ? opportunities.opportunities.length ? <table className={styles.candidates}><caption className={styles.srOnly}>탐색 후보 가격 변화 · 목록 순서 상위 4개</caption><thead><tr><th scope="col">종목</th><th scope="col">1일 변화</th><th scope="col">5일 변화</th><th scope="col">시스템 판단</th></tr></thead><tbody>{opportunities.opportunities.slice(0, 4).map((item) => <tr key={item.ticker}>
              <th scope="row"><Link href={`/ticker/${encodeURIComponent(item.ticker)}`}>{item.ticker}</Link></th><td className={styles.change} data-direction={item.change_1d == null ? "unknown" : item.change_1d > 0 ? "up" : item.change_1d < 0 ? "down" : "flat"}>{displayChange(item.change_1d)}</td><td className={styles.change} data-direction={item.change_5d == null ? "unknown" : item.change_5d > 0 ? "up" : item.change_5d < 0 ? "down" : "flat"}>{displayChange(item.change_5d)}</td>
              <td><DetailDialog label={item.verdict.split("—")[0].trim()} title={`${item.ticker} · 탐색 근거`}><p>{item.verdict}</p><h3>긍정 근거</h3><ul>{item.pros.length ? item.pros.map((reason, i) => <li key={i}>{reason}</li>) : <li>제공된 근거 없음</li>}</ul><h3>유의점</h3><ul>{item.cons.length ? item.cons.map((reason, i) => <li key={i}>{reason}</li>) : <li>제공된 유의점 없음</li>}</ul><p className={styles.basis}>탐색 후보의 가격 변화입니다. 신규 판단이나 판단 변경을 의미하지 않습니다.</p><p className={styles.basis}>목록 생성 · {displayTime(opportunities.generated_at)} · 개별 가격 관측 시각은 제공되지 않습니다.</p><Link href={`/ticker/${encodeURIComponent(item.ticker)}`} className={styles.textLink}>종목 상세 <ArrowUpRight size={14} /></Link></DetailDialog></td>
            </tr>)}</tbody></table> : <Empty /> : <Empty failed />}
          </div>
          <p className={styles.panelFooter}>후보 가격 변화 · 판단 변경 이력 아님</p>
        </section>

        <section id="trust" className={styles.panel}>
          <div className={styles.panelHeading}><h2><ShieldCheck size={14} />데이터 업데이트</h2><DetailDialog label="전체 소스 ↗" title="데이터 소스별 신선도">
            {freshness?.details.length ? freshness.details.map((item) => <div className={styles.sourceRow} key={item.key}><span><b>{item.label}</b><small>{item.message || displayTime(item.last_updated)}</small></span><span className={styles.badge} data-tone={item.status === "FAIL" ? "danger" : item.status === "WARN" ? "warning" : "neutral"}>{statusLabels[item.status] || item.status}</span></div>) : <Empty failed={!freshness} />}
            {!!dashboard?.verdict_stale_inputs?.length && <p className={styles.caution}>종합 의견 보류 입력: {dashboard.verdict_stale_inputs.map((item) => item.label).join(" · ")}</p>}
          </DetailDialog></div>
          <div className={styles.panelBody}>
            <div className={styles.healthCounts}><span><i data-tone="positive" />정상 <b>{freshness?.pass ?? "—"}</b></span><span><i data-tone="warning" />주의 <b>{freshness?.warn ?? "—"}</b></span><span><i data-tone="danger" />지연 <b>{freshness?.fail ?? "—"}</b></span></div>
            {freshness?.details.length ? <>
              <div className={styles.healthBar} aria-hidden="true">{([['pass', 'positive'], ['warn', 'warning'], ['fail', 'danger']] as const).map(([key, tone]) => <span key={key} data-tone={tone} style={{ flex: freshness[key] }} />)}</div>
              {delayed.slice(0, 2).map((item) => <div className={styles.sourceRow} key={item.key}><span><b>{item.label}</b><small>{item.message || displayTime(item.last_updated)}</small></span><span className={styles.statusDot} data-tone={item.status === "FAIL" ? "danger" : "warning"} /></div>)}
              {!delayed.length && <p className={styles.empty}>주의·지연 항목 없음</p>}
            </> : <Empty failed={!freshness} />}
          </div>
          <div className={`${styles.panelFooter} ${styles.sectionHeading}`}><span>{freshness?.details.length ? `${freshness.details.length}개 소스 모니터링` : "신선도 확인 불가"}</span><RefreshDialog delayedKeys={delayed.map(item => item.key)} label="지연 데이터 갱신 ↗" /></div>
        </section>

        <PipelineStatus initial={pipeline} delayedKeys={delayed.map(item => item.key)} />
      </div>

      <footer className={styles.footer}>
        <span>현재 스냅샷 · {displayTime(actions?.generated_at)}</span>
        <div>
          <DetailDialog label={`시스템 알림 ${dashboard?.alerts.length ?? "—"}`} title="시스템 알림">{dashboard ? dashboard.alerts.length ? dashboard.alerts.map((alert, index) => <p className={styles.note} key={index}>{alert.message}</p>) : <Empty /> : <Empty failed />}</DetailDialog>
          <DetailDialog label="화면 비교 안내" title="기존 화면과 비교">
            <p>동일한 백엔드를 사용하는 별도 화면입니다. 조회 시점에 따라 값이 다를 수 있습니다.</p>
            <ul><li>시장 요약·판단·자산 배분·수집 상태를 한 화면에서 확인합니다.</li><li>판단을 선택하면 근거와 보유 영향이 옆에 표시됩니다.</li><li>추가 근거와 전체 소스는 팝업 또는 상세 화면에서 확인합니다.</li></ul>
            <Link href="/" target="_blank" rel="noopener noreferrer" prefetch={false} className={styles.textLink}>기존 화면을 새 탭에서 열기 <ArrowUpRight size={14} /></Link>
          </DetailDialog>
        </div>
      </footer>
    </div>
  );
}
