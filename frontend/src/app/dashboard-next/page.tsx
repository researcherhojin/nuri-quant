import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowUpRight, ArrowLeftRight, RefreshCw, Activity, Globe2, Info, ListChecks, ShieldCheck, ChartNoAxesCombined, Layers3, ListFilter, Radar } from "lucide-react";
import { DASHBOARD_NEXT as COPY, MACRO_INTERPRETATION, REGIME_LABEL } from "@/lib/strings";
import { actionsSchema, dashboardSchema, displayNumber, displayTime, freshnessSchema, opportunitiesSchema, pipelineSchema, portfolioSchema, readPanel } from "./data";
import { displayChange, displayShortTime } from "./format";
import { Inbox, type Bucket } from "./inbox";
import { PortfolioPanel } from "./portfolio-panel";
import { RefreshDialog } from "./refresh-dialog";
import { PipelineStatus } from "./pipeline-status";
import { DetailDialog } from "./detail-dialog";
import styles from "./dashboard.module.css";
import { lookup } from "@/lib/utils";

export const dynamic = "force-dynamic";

export const metadata = { title: "Overview · Nuri-Quant" };

const buckets: Bucket[] = ["urgent", "check", "portfolio", "hold"];

const PANELS = 6;

function Empty({ failed = false }: { failed?: boolean }) {
  return <p className={styles.empty}>{failed ? COPY.UNAVAILABLE : COPY.EMPTY}</p>;
}

function regimeName(key: string): string {
  return lookup(REGIME_LABEL, key) || key;
}

// 저장된 source 코드 → 표시 이름. 모르는 코드는 그대로 둔다 — 출처를 지어내지 않는다 (#1682)
function sourceName(code: string | null | undefined): string {
  return code ? lookup(COPY.SOURCE_NAME, code) ?? code : COPY.METRICS.SOURCE_UNKNOWN;
}

// 같은 지표라도 출처가 대용치면 이름이 달라진다 — yfinance 의 2년물 자리는 ^IRX(13주물)다 (#1682 Codex P2)
function macroInputLabel(key: string, source: string | null): string {
  return lookup(COPY.MACRO_INPUT_PROXY_LABEL, `${key}:${source ?? ""}`) ?? lookup(COPY.MACRO_INPUT_LABEL, key) ?? key;
}

interface SourceRow {
  key: string;
  item: string;
  source: string;
  date: string | null;
}

// 지표 카드 머리글 — 하단 패널과 같은 "아이콘 + 이름", 설명과 출처는 읽는 법 모달 (#1682)
function MetricHeading({ icon, title, guideTitle, guide, sources, note }: {
  icon: ReactNode;
  title: string;
  guideTitle: string;
  guide: readonly string[];
  sources: SourceRow[];
  note?: string;
}) {
  return (
    <div className={styles.metricHeading}>
      <h2>{icon}{title}</h2>
      <DetailDialog label={COPY.METRICS.GUIDE} icon={<Info size={14} />} title={guideTitle} iconOnly>
        {guide.map((text) => <p key={text}>{text}</p>)}
        <h3>{COPY.METRICS.SOURCE_HEADING}</h3>
        <table className={styles.sourceTable}>
          <thead><tr>{COPY.METRICS.SOURCE_COLUMNS.map((column) => <th key={column} scope="col">{column}</th>)}</tr></thead>
          <tbody>{sources.map((row) => (
            <tr key={row.key}><td>{row.item}</td><td>{row.source}</td><td>{row.date ?? "—"}</td></tr>
          ))}</tbody>
        </table>
        {note && <p>{note}</p>}
      </DetailDialog>
    </div>
  );
}

function direction(value: number | null | undefined) {
  return value == null ? "unknown" : value > 0 ? "up" : value < 0 ? "down" : "flat";
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
  // 백엔드 placeholder(coverage 0 · "Unavailable") 는 점수로 보이지 않는다 — #1026 · #1652 와 같은 규칙
  const macroAvailable = dashboard && dashboard.macro.coverage !== 0 && dashboard.macro.interpretation !== "Unavailable";
  const regimeAvailable = dashboard && dashboard.regime.regime !== "unknown";
  const indices = dashboard?.market_indices ?? [];
  const macroInputs = dashboard?.macro_inputs ?? [];
  const vixInput = macroInputs.find((input) => input.key === "vix");

  // 판정 기준일 — 목록 생성 시각(generated_at)은 조회할 때마다 "지금" 이라 판정의 나이를 말해 주지 않는다
  const judgedAt = [...(actions?.urgent ?? []), ...(actions?.check ?? []), ...(actions?.portfolio ?? [])]
    .flatMap((item) => (item.as_of ? [item.as_of.slice(0, 10)] : []))
    .sort()
    .at(-1) ?? null;

  const macroSources = [...new Set(macroInputs.flatMap((input) => (input.source ? [sourceName(input.source)] : [])))];
  // 특수 레짐일 때만 기본 판정(추세 × 변동성)을 따로 보인다 — 기본 레짐이면 같은 말의 반복이다
  const baseKey = dashboard?.regime.volatility ? `${dashboard.regime.trend}_${dashboard.regime.volatility}_vol` : null;
  const baseRegime = regimeAvailable && baseKey && baseKey !== dashboard.regime.regime ? baseKey : null;
  const delayed = freshness?.details.filter((item) => item.status !== "PASS").sort((a, b) => Number(b.status === "FAIL") - Number(a.status === "FAIL")) ?? [];
  const delayedKeys = delayed.map((item) => item.key);

  const reliability = !freshness?.details.length
    ? COPY.SUMMARY.FRESHNESS_UNKNOWN
    : freshness.fail > 0 ? COPY.SUMMARY.FRESHNESS_FAIL(freshness.fail)
    : freshness.warn > 0 ? COPY.SUMMARY.FRESHNESS_WARN(freshness.warn)
    : COPY.SUMMARY.FRESHNESS_OK;

  const restricted = dashboard?.verdict_level === "stale";
  const count = (n: number | undefined) => (n == null ? "—" : String(n));

  return (
    <div className={styles.dashboard} data-testid="overview-dashboard">
      <header className={styles.header}>
        <div className={styles.titleGroup}>
          <h1>{COPY.TITLE}</h1>
          <span className={styles.preview}>{COPY.PREVIEW_TAG}</span>
          <p>{COPY.SUBTITLE}</p>
        </div>
        <div className={styles.headerActions}>
          <Link href="/" prefetch={false} className={styles.button}><ArrowLeftRight size={14} />{COPY.COMPARE}</Link>
          <a href="/dashboard-next" className={styles.iconButton} aria-label={COPY.REFRESH}><RefreshCw size={15} /></a>
        </div>
      </header>

      <section className={styles.summary} aria-label={COPY.SUMMARY.ARIA}>
        <div className={styles.verdict}>
          <span className={styles.statusDot} data-tone={restricted ? "warning" : "neutral"} />
          <span className={styles.summaryLabel}>{COPY.SUMMARY.LABEL}</span>
          <p>{dashboard?.verdict || COPY.UNAVAILABLE}</p>
        </div>
        <a href="#trust" className={styles.reliability} data-health={freshness?.details.length && !delayed.length ? "ready" : "attention"}><ShieldCheck size={14} />{reliability}</a>
        {missing > 0 && <p role="status" className={styles.warning}>{COPY.SUMMARY.PARTIAL(missing, PANELS)} {COPY.UNAVAILABLE}</p>}
      </section>

      <div className={styles.metrics} aria-label={COPY.METRICS.ARIA}>
        {/* 머리글은 공식 지수, 레짐은 아래 시스템 분류 한 줄 — 배분을 정하므로 지우지 않는다 (#1676).
            네 카드 모두 아이콘 + 이름 머리글, 설명·출처는 읽는 법 모달, 우측 하단에 출처 요약 (#1682) */}
        <article className={styles.marketCard} aria-label={COPY.METRICS.INDICES}>
          <MetricHeading
            icon={<Globe2 size={14} />}
            title={COPY.METRICS.INDICES}
            guideTitle={COPY.METRICS.REGIME_GUIDE_TITLE}
            guide={COPY.METRICS.REGIME_GUIDE}
            sources={indices.map((index) => ({ key: index.key, item: index.label, source: `${sourceName(index.source)}${index.symbol ? ` ${index.symbol}` : ""}`, date: index.date }))}
          />
          {indices.length ? (
            <ul className={styles.indices}>{indices.map((index) => (
              <li key={index.key}>
                {/* 기준일은 이름 줄에 MM-DD 로 — 등락률 줄에 두면 좁은 폭(1280)에서 옆 칸 숫자와 붙는다 */}
                <span className={styles.indexHead}><b>{index.label}</b> {index.date ? <time dateTime={index.date}>{index.date.slice(5)}</time> : <time>{COPY.METRICS.INDEX_DATE_UNKNOWN}</time>}</span>
                <strong>{displayNumber(index.close, "", 2)}</strong>
                <span className={styles.indexChange}>
                  <span className={styles.change} data-direction={direction(index.change_pct)}>{displayChange(index.change_pct, 2)}</span>
                </span>
              </li>
            ))}</ul>
          ) : <p className={styles.indexEmpty}>{COPY.METRICS.INDICES_UNAVAILABLE}</p>}
          <div className={styles.metricFoot}>
            <span className={styles.regimeLine}>
              {COPY.METRICS.REGIME}
              <b>{regimeAvailable ? regimeName(dashboard.regime.regime) : "—"}</b>
              {/* confidence 는 기본 판정의 추세 검사 + VIX·밴드폭 변동성 교차 검사 중 통과 비율이다(값 없는 검사는 분모에서 빠짐) — 특수 분류 옆에 "신뢰도" 로 두면 그 분류의 확신처럼 읽힌다 */}
              <small>{[baseRegime ? COPY.METRICS.REGIME_BASE(regimeName(baseRegime)) : null, COPY.METRICS.REGIME_AGREEMENT(displayNumber(regimeAvailable ? dashboard.regime.confidence : null, "%"))].filter(Boolean).join(" · ")}</small>
            </span>
            <span className={styles.metricSource}>{[...new Set(indices.map((index) => sourceName(index.source)))].join(" · ")}</span>
          </div>
        </article>
        <article>
          <MetricHeading
            icon={<ChartNoAxesCombined size={14} />}
            title={COPY.METRICS.MACRO}
            guideTitle={COPY.METRICS.MACRO_GUIDE_TITLE}
            guide={COPY.METRICS.MACRO_GUIDE}
            sources={macroInputs.map((input) => ({ key: input.key, item: macroInputLabel(input.key, input.source), source: sourceName(input.source), date: input.date }))}
            note={COPY.METRICS.SOURCE_EVENT_NOTE}
          />
          <strong>{displayNumber(macroAvailable ? dashboard.macro.score : null)}<span>{COPY.METRICS.MACRO_DENOMINATOR}</span></strong>
          <div className={styles.metricFoot}>
            <small>{macroAvailable ? lookup(MACRO_INTERPRETATION, dashboard.macro.interpretation) || dashboard.macro.interpretation : COPY.METRICS.MACRO_UNAVAILABLE}</small>
            <span className={styles.metricSource}>{macroSources.length ? COPY.METRICS.SOURCE_MORE(macroSources[0], macroSources.length - 1) : COPY.METRICS.SOURCE_UNKNOWN}</span>
          </div>
        </article>
        <article>
          <MetricHeading
            icon={<Activity size={14} />}
            title={COPY.METRICS.VIX}
            guideTitle={COPY.METRICS.VIX_GUIDE_TITLE}
            guide={COPY.METRICS.VIX_GUIDE}
            sources={vixInput ? [{ key: "vix", item: "VIX", source: sourceName(vixInput.source), date: vixInput.date }] : []}
          />
          <strong>{displayNumber(dashboard?.regime.vix)}</strong>
          <div className={styles.metricFoot}>
            <small>{COPY.METRICS.VIX_SUB}</small>
            <span className={styles.metricSource}>{vixInput ? `${sourceName(vixInput.source)} · ${vixInput.date?.slice(5) ?? "—"}` : COPY.METRICS.SOURCE_UNKNOWN}</span>
          </div>
        </article>
        <article>
          <MetricHeading
            icon={<ListChecks size={14} />}
            title={COPY.METRICS.ACTIONS}
            guideTitle={COPY.METRICS.ACTIONS_GUIDE_TITLE}
            guide={COPY.METRICS.ACTIONS_GUIDE}
            sources={[{ key: "actions", item: COPY.METRICS.ACTIONS_JUDGED, source: COPY.METRICS.ACTIONS_SOURCE, date: judgedAt }]}
            note={COPY.METRICS.SOURCE_LIST_GENERATED(displayShortTime(actions?.generated_at) ?? "—")}
          />
          <strong>{count(actions?.urgent.length)}<span>{COPY.METRICS.ACTIONS_UNIT}</span></strong>
          <div className={styles.metricFoot}>
            <small>{COPY.METRICS.ACTIONS_SUB(count(actions?.check.length), count(actions?.portfolio.length))}</small>
            <span className={styles.metricSource}>{COPY.METRICS.ACTIONS_JUDGED_SHORT(judgedAt?.slice(5) ?? "—")}</span>
          </div>
        </article>
      </div>

      <div className={styles.primaryGrid}>
        <section id="review" className={`${styles.panel} ${styles.reviewPanel}`}>
          <div className={styles.panelHeading}>
            <h2><ListFilter size={14} />{COPY.INBOX}</h2>
            <div className={styles.pipelineControls}>
              <DetailDialog label={COPY.INBOX_PANEL.GUIDE} icon={<Info size={14} />} title={COPY.INBOX_PANEL.GUIDE_TITLE} iconOnly>
                <p>{COPY.INBOX_PANEL.GUIDE_INTRO}</p>
                <ul>{COPY.INBOX_PANEL.GUIDE_BUCKETS.map((text) => <li key={text}>{text}</li>)}</ul>
                <p>{COPY.INBOX_PANEL.GUIDE_AXES}</p>
                <p>{COPY.INBOX_PANEL.GUIDE_CAVEAT}</p>
              </DetailDialog>
              <Link href="/decisions" className={styles.textLink}>{COPY.INBOX_PANEL.LEDGER} <ArrowUpRight size={14} /></Link>
            </div>
          </div>
          <Inbox key={bucket} actions={actions} initialBucket={bucket} />
        </section>
        <section className={styles.panel} aria-label={COPY.PORTFOLIO.ARIA}>
          <div className={styles.panelHeading}>
            <h2><Layers3 size={14} />{COPY.ALLOCATION}</h2>
            <Link href="/portfolio" className={styles.textLink}>{COPY.PORTFOLIO.VIEW_ALL} <ArrowUpRight size={14} /></Link>
          </div>
          <PortfolioPanel portfolio={portfolio} exchangeRate={dashboard?.exchange_rate} />
          <Link href="/dashboard-next?bucket=portfolio" prefetch={false} className={styles.ruleLink}>
            <span>{COPY.PORTFOLIO.RULES_LINK} <b>{COPY.PORTFOLIO.RULES_COUNT(count(actions?.portfolio.length))}</b></span>
            <ArrowUpRight size={15} />
          </Link>
        </section>
      </div>

      <div className={styles.secondaryGrid}>
        <section className={styles.panel} aria-label={COPY.RADAR_PANEL.ARIA}>
          <div className={styles.panelHeading}>
            <h2><Radar size={14} />{COPY.RADAR}</h2>
            <Link href="/scan" className={styles.textLink}>{COPY.RADAR_PANEL.SCANNER} <ArrowUpRight size={14} /></Link>
          </div>
          <div className={styles.panelBody}>
            {opportunities ? opportunities.opportunities.length ? (
              <table className={styles.candidates}>
                <caption className={styles.srOnly}>{COPY.RADAR_PANEL.CAPTION}</caption>
                <thead><tr>
                  <th scope="col">{COPY.RADAR_PANEL.COL_TICKER}</th>
                  <th scope="col">{COPY.RADAR_PANEL.COL_1D}</th>
                  <th scope="col">{COPY.RADAR_PANEL.COL_5D}</th>
                  <th scope="col">{COPY.RADAR_PANEL.COL_VERDICT}</th>
                </tr></thead>
                <tbody>{opportunities.opportunities.slice(0, 4).map((item) => (
                  <tr key={item.ticker}>
                    <th scope="row"><Link href={`/ticker/${encodeURIComponent(item.ticker)}`}>{item.ticker}</Link></th>
                    <td className={styles.change} data-direction={direction(item.change_1d)}>{displayChange(item.change_1d)}</td>
                    <td className={styles.change} data-direction={direction(item.change_5d)}>{displayChange(item.change_5d)}</td>
                    <td>
                      <DetailDialog label={item.verdict.split("—")[0].trim()} title={COPY.RADAR_PANEL.DETAIL_TITLE(item.ticker)}>
                        <p>{item.verdict}</p>
                        <h3>{COPY.RADAR_PANEL.PROS}</h3>
                        <ul>{item.pros.length ? item.pros.map((reason, i) => <li key={i}>{reason}</li>) : <li>{COPY.RADAR_PANEL.NO_PROS}</li>}</ul>
                        <h3>{COPY.RADAR_PANEL.CONS}</h3>
                        <ul>{item.cons.length ? item.cons.map((reason, i) => <li key={i}>{reason}</li>) : <li>{COPY.RADAR_PANEL.NO_CONS}</li>}</ul>
                        <p className={styles.basis}>{COPY.RADAR_PANEL.NOT_A_DECISION}</p>
                        <p className={styles.basis}>{COPY.RADAR_PANEL.GENERATED(displayTime(opportunities.generated_at))}</p>
                        <Link href={`/ticker/${encodeURIComponent(item.ticker)}`} className={styles.textLink}>{COPY.RADAR_PANEL.TICKER_DETAIL} <ArrowUpRight size={14} /></Link>
                      </DetailDialog>
                    </td>
                  </tr>
                ))}</tbody>
              </table>
            ) : <Empty /> : <Empty failed />}
          </div>
          <p className={styles.panelFooter}>{COPY.RADAR_PANEL.FOOTER}</p>
        </section>

        <section id="trust" className={styles.panel}>
          <div className={styles.panelHeading}>
            <h2><ShieldCheck size={14} />{COPY.TRUST}</h2>
            <DetailDialog label={COPY.TRUST_PANEL.ALL_SOURCES} icon={<ArrowUpRight size={12} />} title={COPY.TRUST_PANEL.ALL_SOURCES_TITLE}>
              {freshness?.details.length ? freshness.details.map((item) => (
                <div className={styles.sourceRow} key={item.key}>
                  <span><b>{item.label}</b><small>{item.message || displayTime(item.last_updated)}</small></span>
                  <span className={styles.badge} data-tone={item.status === "FAIL" ? "danger" : item.status === "WARN" ? "warning" : "neutral"}>{lookup(COPY.STATUS, item.status) || item.status}</span>
                </div>
              )) : <Empty failed={!freshness} />}
              {!!dashboard?.verdict_stale_inputs?.length && <p className={styles.caution}>{COPY.TRUST_PANEL.STALE_INPUTS}{dashboard.verdict_stale_inputs.map((item) => item.label).join(" · ")}</p>}
            </DetailDialog>
          </div>
          <div className={styles.panelBody}>
            <div className={styles.healthCounts}>
              <span><i data-tone="positive" />{COPY.TRUST_PANEL.PASS} <b>{freshness?.pass ?? "—"}</b></span>
              <span><i data-tone="warning" />{COPY.TRUST_PANEL.WARN} <b>{freshness?.warn ?? "—"}</b></span>
              <span><i data-tone="danger" />{COPY.TRUST_PANEL.FAIL} <b>{freshness?.fail ?? "—"}</b></span>
            </div>
            {freshness?.details.length ? <>
              <div className={styles.healthBar} aria-hidden="true">{([["pass", "positive"], ["warn", "warning"], ["fail", "danger"]] as const).map(([key, tone]) => <span key={key} data-tone={tone} style={{ flex: freshness[key] }} />)}</div>
              {delayed.slice(0, 2).map((item) => (
                <div className={styles.sourceRow} key={item.key}>
                  <span><b>{item.label}</b><small>{item.message || displayTime(item.last_updated)}</small></span>
                  <span className={styles.statusDot} data-tone={item.status === "FAIL" ? "danger" : "warning"} />
                </div>
              ))}
              {!delayed.length && <p className={styles.empty}>{COPY.TRUST_PANEL.NONE_DELAYED}</p>}
            </> : <Empty failed={!freshness} />}
          </div>
          <div className={`${styles.panelFooter} ${styles.sectionHeading}`}>
            <span>{freshness?.details.length ? COPY.TRUST_PANEL.MONITORED(freshness.details.length) : COPY.TRUST_PANEL.UNKNOWN}</span>
            <RefreshDialog delayedKeys={delayedKeys} label={COPY.TRUST_PANEL.REFRESH_DELAYED} />
          </div>
        </section>

        <PipelineStatus initial={pipeline} delayedKeys={delayedKeys} />
      </div>

      <footer className={styles.footer}>
        <span>{COPY.FOOTER.SNAPSHOT}{displayTime(actions?.generated_at)}</span>
        <div>
          <DetailDialog label={COPY.FOOTER.ALERTS(count(dashboard?.alerts.length))} title={COPY.FOOTER.ALERTS_TITLE}>
            {dashboard ? dashboard.alerts.length ? dashboard.alerts.map((alert, index) => <p className={styles.note} key={index}>{alert.message}</p>) : <Empty /> : <Empty failed />}
          </DetailDialog>
          <DetailDialog label={COPY.FOOTER.COMPARE_GUIDE} title={COPY.FOOTER.COMPARE_TITLE}>
            <p>{COPY.FOOTER.COMPARE_INTRO}</p>
            <ul>{COPY.FOOTER.COMPARE_POINTS.map((text) => <li key={text}>{text}</li>)}</ul>
            <Link href="/" target="_blank" rel="noopener noreferrer" prefetch={false} className={styles.textLink}>{COPY.FOOTER.OPEN_LEGACY} <ArrowUpRight size={14} /></Link>
          </DetailDialog>
        </div>
      </footer>
    </div>
  );
}
