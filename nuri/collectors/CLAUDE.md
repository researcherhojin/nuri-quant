# nuri/collectors/ — 27 Data Collectors

## BaseCollector Contract

All collectors inherit `BaseCollector` (`base.py`):

1. Implement `collect(**kwargs) -> Any` — fetch data from external source
2. Implement `save(data) -> int` — persist to DB via `nuri/core/db/` package functions
3. External code calls `run()` which does `collect()` → `save()` with logging and timing

## Korean Ticker `.KS` Suffix Convention (canonical)

Korean equities are addressed by KRX 6-digit code suffixed with `.KS` (e.g., `005930.KS` for 삼성전자). yfinance accepts the suffix and returns:

- ✅ Price history (`Ticker.history`), volume, dividend events
- ✅ Fundamentals (`Ticker.info`) for individual stocks: PE, ROE, margins, growth, debt — **but `trailingPE` is NOT provided for KR individuals** (yfinance provider limit). Use `forward_pe` instead (182/209 KR coverage as of 2026-07-08 dev DB — live number, re-probe before citing).
- ❌ Fundamentals for ETFs return empty (expected — ETF wrapper, no underlying P&L).

KIS Open API is NOT needed for KR fundamentals (was previously believed required — corrected during #418 KIS Open API integration audit).

## Ticker Filtering + Source

`_get_tickers(market=, source=)` (#272 Phase 2b):
- `market`: `"us"` (excludes KR) | `"kr"` (KR only) | `None` (전체). KR 판정은 canonical `is_kr_ticker()` — `.KS` **및** `.KQ` (#764). `.KS` 로만 필터하면 KOSDAQ 이 kr 에서 누락되고 동시에 `not .KS` 인 us 로 새어 미국장 시간대(KOSDAQ 휴장)에 수집된다.
  **Test:** `tests/collectors/test_base.py::TestGetTickers::test_kosdaq_routes_to_kr_not_us` — 양방향 잠금(한쪽만 보면 반대 회귀가 통과한다).
- `source`: `"portfolio"` (default, 보유종목 — `SELECT FROM portfolio`) | `"universe"` (`config/universe.yaml` 전체 ~746) | `"all"` (union)

CLI: `--source` flag is the standard way to switch (stock, stock_kr, fundamental, wallstreet, estimates, technical, events, news).

**KR reference tickers bypass `source` entirely.** `stock_kr.collect()` unions `_reference_tickers()` (derived from `rules.yaml brief.benchmark.kr`) into every run. The KR benchmark is not a holding, so `portfolio` misses it, and `universe.yaml` is auto-synced from KRX constituents so a hand-added ETF is wiped by the next `make universe-sync` — it was collected by neither path and sat at **0 rows in production** while four consumers read it (brief benchmark, sector-mover fallback, events, risk_signals). Derived from config, not a second hardcoded list, so changing the benchmark moves collection with it.
**Test:** `tests/collectors/test_stock_kr.py::TestStockKRCollectorScenarios::test_collect_without_kr_holdings_still_gets_reference` — dropping the union returns an empty frame again.

## Parallelism Pattern (yfinance vs KRX) ⚠️

**yfinance**: 10 concurrent threads OK. Use `ThreadPoolExecutor(max_workers=10)`.
**KRX (pykrx)**: rate-limits aggressively. Use sequential + 100ms delay.

| Collector | Source | Parallelism | Why |
|-----------|--------|-------------|-----|
| stock, fundamental, wallstreet, estimates | yfinance | **10 threads** | API tolerates concurrency |
| stock_kr | pykrx (KRX) | **sequential + 0.1s sleep** | First ~60 fast then server hangs |
| ark, finviz | ark-funds.com CSV / finviz | small loop | <20 items, no benefit |

Standard parallel pattern (consistent across yfinance collectors):
```python
def _fetch_one(ticker: str) -> tuple[str, ...]:
    """Returns (ticker, result, status)."""
    ...

with ThreadPoolExecutor(max_workers=10) as ex:
    futures = {ex.submit(_fetch_one, t): t for t in tickers}
    for fut in tqdm(as_completed(futures), total=len(tickers), desc=...):
        ticker, result, status = fut.result()
        ...  # aggregate in main thread
```

ThreadPoolExecutor caveat: `.result(timeout=)` cancels FUTURE only — underlying C extension call (e.g. pykrx) keeps running. **Don't rely on timeout for cancellable hangs**. Sequential + delay for hanging APIs (KRX).

## OpenBB Local Import Pattern

`obb` is imported **inside functions**, not at module level. This means:
- `patch("module.obb")` will FAIL — the name doesn't exist at module level
- Use `patch.dict(sys.modules, {"openbb": mock_module})` for testing

## OpenBB Provider Limitations

| Endpoint | yfinance | Paid alternative |
|----------|----------|-----------------|
| `obb.equity.price.historical` | OK | — |
| `obb.equity.fundamental.metrics` | OK | — |
| `obb.equity.estimates.consensus` | OK | — |
| `obb.equity.fundamental.ratios` | No | `fmp` / `intrinio` |
| `obb.equity.estimates.price_target` | No | `benzinga` / `fmp` |
| `obb.equity.ownership.*` | No | `fmp` |

## 전면 실패는 빈 수집과 다르다 (#1043)

수집기가 **모든 엔드포인트에서 실패**했는데 `[]` 를 반환하면, 보고할 게 없던 날과
DB 기록이 **완전히 같아진다** — 둘 다 warning 만 남기고 `collector_runs.status` 는
`finished` 다. coingecko 는 `rows_collected` 가 `run_step` 이 돌려주는 4-key dict 의
길이라 **항상 4**여서, status 가 유일한 판별자인데 그게 성공이라고 말하고 있었다.

전면 실패 시 **raise 한다.** 새 장치를 만드는 게 아니라 이미 있으면서 우회되던 것들을
되살리는 것이다 — `base.py` 의 3회 재시도, `_send_failure_alert()` 의 `#ops` 알림,
scheduler 의 `status="failed"` + `error_message`, `step_failed` 파이프라인 이벤트,
`collector_health` 의 실패 집계.

두 가지가 미묘하다:
- 조건은 `len(errors) == 2` 가 아니라 **`errors and not records`** — 한쪽이 예외이고
  다른 쪽이 빈 응답인 경우도 실패다. 반대로 **둘 다 200 인데 본문이 비면** 예외가
  없어 `[]` 가 그대로 나간다. 그게 NO_DATA 의 정의다.
- `errors[-1]` 이 아니라 **`errors[0]`** 을 올린다. 둘 다 실패하면 마지막은 항상
  global 이라, price 의 429 가 알림 문구에서 사라지고 운영자가 엉뚱한 원인을 좇는다.

**Test:** `tests/collectors/test_coingecko.py::TestCoinGeckoFailedVsNoData` —
`test_total_api_failure_raises_instead_of_returning_empty` (raise 제거 시 FAIL) ·
`test_empty_payload_is_not_a_failure` (조건을 `errors` 로 넓히면 FAIL) ·
`test_first_error_is_raised_not_the_last` (`errors[0]`→`errors[-1]` 이면 FAIL).

**형제 둘도 같은 규약으로 정렬됨 (#1042)** — `fear_greed.py` 와 `cboe.py`. 새 수집기를
쓰거나 기존 것을 고칠 때 이 구분이 서 있는지 먼저 볼 것.

`fear_greed` 는 coingecko 와 같은 `errors and not records` 를 쓴다. API 가 200 인데
`fear_and_greed` 키가 없으면 예외가 없으니 `[]` 가 그대로 나가고 폴백도 안 탄다(NO_DATA).
API 가 죽은 뒤 스크래핑이 **예외 없이 점수를 못 찾은** 경우는 실패로 친다 — 앞에서 이미
예외가 났기 때문이다.
**Test:** `tests/collectors/test_fear_greed.py::TestFearGreedFailedVsNoData` —
`test_total_failure_raises_instead_of_returning_empty`(raise 제거 시 FAIL) ·
`test_empty_payload_is_not_a_failure`(조건을 `not records` 로 넓히면 FAIL) ·
`test_first_error_is_raised_not_the_last`(`errors[0]`→`errors[-1]` 이면 FAIL) ·
`test_scrape_fallback_still_rescues_a_dead_api`(과잉 차단 방지).

`cboe` 는 조건이 `errors` 뿐이다 — 5개 티어가 값을 건지면 즉시 return 하므로 마지막 줄에
닿았다는 것 자체가 이미 "한 건도 못 건졌다" 는 뜻이고, `not records` 를 덧붙이면 records
가 비지 않을 수도 있다는 잘못된 인상만 준다.

⚠️ **cboe 에서 이 raise 는 좀처럼 안 터진다 — 그리고 그건 의도다.** 5차
`_collect_db_stale` 이 DB 에 이전 값이 하나라도 있으면 성공으로 돌려주므로, 라이브 소스 4개가
전부 죽어도 마지막 줄까지 안 온다. 즉 **"DB_STALE 재사용이 영원히 성공으로 집계되는" 축은
그대로 남아 있다** — `put_call_ratio` 는 `nuri/core/freshness.py FRESHNESS_POLICIES` 에
항목이 없어 아무도 그 stale 을 감시하지 않고, 실제로 프로덕션에 6주 구멍
(2026-06-22→2026-08-03)이 무발화로 지나갔다. 별건이며 #1042 밖이다.
**Test:** `tests/collectors/test_cboe.py::TestCBOEFailedVsNoData::test_db_stale_still_counts_as_success`
— 이 한계를 명시적으로 잠근다(조용히 바꾸면 라이브 소스가 흔들릴 때마다 수집기가 죽는다).

## ARK: 보유 스냅샷이지 매매 내역이 아니다 (`ark.py`, #1143)

ARK 는 **일별 보유 CSV** 를 낸다. 매매 내역 파일(`ARK_TRADE.csv`)은 없어졌다.
그래서 `direction` 은 받아 적는 값이 아니라 **직전 수집분 대비 `shares` 증감으로
파생**한다. `config/rules.yaml ark.min_trade_pct`(1.0%) 미만은 Hold — ARK 는
리밸런싱으로 매일 소수점 수준을 움직여서, 0 이 아닌 모든 변화를 매매라 부르면 전 종목이
매일 신호를 낸다. 이 값이 smart_money 의 ARK 항목 발화 여부를 직접 결정하므로 코드 상수가
아니라 config 에 있다 (Config over code).

⚠️ **부재는 CSV 에 행으로 나타나지 않는다.** ARK 가 한 종목을 완전히 털면 그냥 사라지므로,
오늘 행만 훑는 파생은 가장 강한 신호인 **전량 청산을 통째로 놓친다** (펀드 간 이동도 같은
구멍 — 떠난 펀드엔 아무 일도 없고 새 펀드엔 첫 관측이라 Hold). `_exit_records()` 가 직전
수집분에 있었는데 오늘 없는 종목을 `Sell` / `shares=0.0` 으로 적는다. 그 0 행은 다시
"여기서 0 이 됐다" 는 기록이 되어, 재진입 때 기준선 조회가 첫 관측으로 되돌린다 — pre-exit
규모와 비교하면 **더 작게 재진입한 것이 Sell 로 뒤집힌다.** 같은 이유로 `shares` 파싱 실패는
0.0 이 아니라 **행 폐기**다: 0 으로 눕히면 소스 포맷 드리프트가 전량 청산으로 읽힌다.
CSV 에서 한 건도 못 건지면 청산 판정 자체를 하지 않는다 (그건 소스 문제지 ARK 의 매도가 아니다).

소스는 펀드별 `assets.ark-funds.com/fund-documents/funds-etf-csv/...` 5개다.
컬럼이 소문자이고 `weight (%)` 이며 `Direction` 이 없다 — 예전 통합 CSV 의
`Ticker` / `% of ETF` 표기와 다르다. 마지막 행은 면책 문구 한 줄이고 비상장 보유분은
ticker 가 비어 있는데, 둘 다 ticker 빈 값으로 자연히 걸러진다.

⚠️ **폴백이 신호 아닌 것을 신호 자리에 쓰면, 소비자는 그걸 신호로 읽는다.**
죽은 CSV 를 메우던 yfinance 폴백은 `top_holdings`(상위 10개)를 `direction="Hold"` /
`shares=0.0` 으로 적었다. 그 자체로는 조용한 결손처럼 보였지만, `smart_money.py` 가
`sells = len(rows) - buys` 로 세고 있어서 **Hold 가 전부 매도로 집계**됐다 — ark
테이블에 있는 티커는 예외 없이 `score -1` 과 "ARK 최근 매도 N건" 이라는 거짓 근거를
받았고, `config/agents.yaml` 의 `score_sell = -1` 이라 그 하나로 verdict 가 SELL 로
넘어갈 수 있었다. 결손이 아니라 **틀린 신호**였고, 헬스체크는 내내 초록이었다.
폴백은 제거했다 (`shares=0.0` 이 델타 기준선까지 오염시킨다 — 기준선 쿼리가
`shares > 0` 을 거는 이유).

⚠️ **소스는 200 인 채로 내용만 언다** (#1145). ARKF 는 7.5개월 전 보유를 담은 CSV 를 정상
서빙하고 있었다 — 다운로드도 파싱도 성공하므로 수집기 실패율에도 `collector_runs` 에도 안
걸린다. 저장 자체는 정확하다(그날 그렇게 들고 있던 게 맞다). 문제는 **그 펀드가 멈춘 걸
아무도 모른다**는 것이다. 두 겹으로 본다: 수집 시점의 펀드별 지연 경고(`_warn_stale_funds`,
임계 `config/rules.yaml ark.max_source_lag_days`)와 `freshness.py` 의 `ark` 정책.

**정책은 `ark` 테이블을 보지 않는다** (#1147). 거기엔 보유 종목과 겹치는 행만 들어가므로,
펀드별 `MAX(date)` 가 재는 것은 *"이 펀드가 마지막으로 발행한 날"* 이 아니라 **"우리가 이 펀드
종목을 마지막으로 들고 있던 날"** 이다. ARKG 는 CSV 를 매일 갱신하는데 우리가 그 보유 종목을
안 들어서 4개월째 행이 없었고, 정책이 **멀쩡한 펀드를 가장 낡았다고 지목**했다 — 소스 감시가
우리 포트폴리오 구성에 의존해버린 것이다. 그래서 수집기가 필터와 무관하게 펀드별 발행일을
전용 테이블 `ark_source_dates`(마이그레이션 55)에 남기고 (`_record_source_dates`), 정책은
그걸 읽는다.

⚠️ **`external_analysis` 에 얹지 않는다.** 거기 `ticker` 는 **실제 종목 심볼 네임스페이스**이고
`ARKK`/`ARKF` 는 진짜 ETF 티커다. 펀드명을 그 컬럼에 쓰면 `get_external()` ·
`/api/external/{ticker}` · `get_external_summary()` 가 이걸 해당 ETF 에 대한 외부 분석으로
돌려주고, 무엇보다 `certification.py` 의 `_count_external_for_class()` 가 **SIEGE external
evidence 로 센다** (그 ETF 를 보유하게 되는 순간). 메타데이터가 신호 자리로 새는 형태다.

⚠️ **정책 쿼리의 `COUNT(*) = 5` 는 장식이 아니다.** 그게 없으면 한 펀드의 행이 **아예 없을 때**
`MIN` 이 남은 펀드들만 보고 초록을 준다 — 새 펀드를 추가했는데 수집이 한 번도 성공 못 한
경우가 정확히 그 모양이다. **부재는 최신이 아니라 미상이고, 미상은 통과가 아니다.**

**그 위에서 `MIN(펀드별 MAX)` 인 이유**: 맨 `MAX` 는 **초록**이다 — 멀쩡한 펀드 4개가 죽은
펀드 하나를 가린다. `signals` 정책이 KR/US 를 안 합치는 것과 같은 축이고, 여기서는 펀드가 그
축이다. 범위는 추적 5개 펀드로 좁힌다 — 전 값을 그룹핑하면 오타나 과거 실험이 남긴 stray
그룹 하나가 정책을 영구 빨강으로 못박고, 영구 빨강 게이트는 아무도 안 보므로 죽은 게이트와
같아진다.

⚠️ **기록 쪽과 판정 쪽의 배선은 따로 잠근다.** 메서드를 직접 부르는 테스트는 `collect()` 에서
호출 한 줄을 지워도 초록이다 — 이 파일에서 두 번(`_warn_stale_funds`, `_record_source_dates`)
그 상태로 통과했다. 배선이 끊기면 정책은 영원히 "데이터 없음" 이고 아무도 눈치채지 못한다.

⚠️ **CSV 날짜는 보유 종목 필터보다 먼저 읽는다.** 필터 뒤에서 읽으면 우리가 아무것도 안
겹치는 펀드는 records 가 비어 `fund_date` 가 안 생기고, 아무리 낡아도 검사에 안 걸린다 —
**소스 감시가 우리 포트폴리오 구성에 의존해버린다.** ARKF 가 그 상태로 미끄러지는 데 필요한
건 우리가 ARKF 보유 종목을 하나도 안 들게 되는 것뿐이다. 그래서 `_collect_fund()` 는
`(records, csv_date)` 를 돌려준다.

**Test:** `tests/collectors/test_ark.py` (파싱 · 방향 파생 · 청산/재진입 5종 · #1043 실패 구분 ·
폴백 부활 감시 — AST 로 본다, 소스의 'yfinance' 는 왜 뺐는지 적은 주석이라 grep 은
영영 빨갛다 · 소스 staleness 4종) + `tests/core/test_ark_freshness_policy.py`
(`test_a_naive_max_date_would_have_passed_the_same_data` 가 정책 쿼리 형태를 못 박는다) + `tests/trading/agents/test_smart_money_branches.py::TestSmartMoneyBranches`
의 `test_ark_hold_rows_are_not_counted_as_sells` ·
`test_ark_counting_is_safe_even_if_the_query_stops_filtering` ·
`test_ark_hold_does_not_crowd_out_real_trades`. 소비자 쪽 방어선은 **둘**이고 막는 게
서로 다르다 — SQL 의 `direction IN ('Buy','Sell')` 이 없으면 최신 Hold 가 `LIMIT 5`
창을 잡아먹어 진짜 매매가 안 보이고(침묵), 집계식이 틀리면 거짓 매도가 나온다.
그래서 집계 쪽 잠금은 `_safe_query` 를 가로채 Hold 행을 집계 코드에 직접 흘린다.

## 13F: 확신 보유 vs 딜러 보유 (`superinvestors.py`, #1098)

한 테이블(`superinvestors`)에 두 종류가 산다. `investor_class` 로 갈린다:

| | `conviction` (기본) | `dealer` |
|---|---|---|
| 누구 | 버핏·달리오·애크먼·국민연금 등 8곳 | JPM·BAC·GS·Citi 4곳 (`BANK_13F`) |
| 수집기 | `SuperinvestorCollector` | `Bank13FCollector` (같은 코드, 클래스 속성만 교체) |
| 의미 | 판단 | 마켓메이킹·수탁·인덱스 혼재 + **45일 지연** |
| 저장 범위 | 전량 | `config/universe.yaml` us 로 제한 |

⚠️ **은행을 확신 신호에 섞으면 틀린 값이 아니라 "변별력 0인 값"이 나온다.** 그래서 화면이
멀쩡해 보인다. `smart_money.py` 는 `score += min(2, 보유 투자자 수)` 인데 은행 4곳은 사실상
미국 유니버스 전체를 들고 있어(실측 2026-08-18: JPM 34,064 · BAC 18,318 · GS 14,070 ·
Citi 11,343 포지션 / 이 테이블 **전체**는 8명 × 10분기 15,600 행) 그 항이 거의 모든 티커에서
상수 2가 된다. `config/rules.yaml min_superinvestors` 도 같이 죽는다. 커버리지 임계(0.80)도
딜러 행이 대신 밟아 확신 13F 수집이 죽어도 초록이 된다.

⚠️ **`INSERT OR REPLACE` 는 컬럼을 빼면 기본값으로 되돌린다.** 재수집마다 `dealer` 행이
조용히 `conviction` 으로 승격됐을 자리다 — upsert 는 `investor_class` 를 반드시 함께 쓴다.

⚠️ **universe 필터는 `portfolio_pct` 계산 뒤**에 건다. 먼저 걸면 분모가 우리 유니버스 합이
되어 비중이 부풀고 "JPM 포트폴리오의 12%" 같은 거짓이 화면에 실린다.

**Test:** `tests/core/test_superinvestor_class_isolation.py` — 동작(딜러 행을 심어도
점수·커버리지 불변)과 구조(`superinvestors` 를 읽는 모든 SQL 리터럴이 `investor_class` 를
걸거나 사유와 함께 allowlist, 양방향)를 같이 잠근다. 뮤테이션 8종 전부 FAIL 실측.
스윕의 한계는 명시돼 있다 — 테이블명이 f-string 변수인 쿼리(`coverage.py::_table_tickers`)는
리터럴에 이름이 없어 안 보이므로 `_COVERAGE_FILTERS` 로 따로 처리했다.

## Macro Data Quirk

`us_3m_yield` (FRED) is absent in yfinance fallback — `^IRX` (13-week T-Bill) is stored as `us_2y_yield`. `merge_macro_data()` queries `us_2y_yield` when `us_3m_yield` is empty.

## Freshness Sentinel Redundancy (#453/#454, post-#457)

SIEGE freshness gate (`certification.py::_check_freshness_for_class`) reads **`prices` only**. `--source freshness` (#457) feeds SPY/TLT/GC=F into `prices` daily. Two known redundancies:

- **`gold` lives in two tables**: `macro.indicator='gold'` (~5Y backfill, 304 rows as of 2026-07-08 — grows daily) AND `prices."GC=F"` (`period=5d` freshness pass, accumulates daily via upsert). Same yfinance source, separate writers (`macro.py` vs `stock.py --source freshness`, wired daily as `stock_us_freshness` in `scheduler.py` #860). No current historical consumer of `prices."GC=F"` beyond the gate, so single-source-of-truth not enforced — accept as debt.
- **TLT shallow history**: `prices.TLT` comes only from the `period=5d` freshness pass. If a future backtest/analysis needs TLT 5Y, add TLT to `universe.yaml` (don't promote freshness gate to dual-source — drift risk per #454 codex consult 2026-04-28).

**Why not dual-source the gate** (option A in #454, rejected): if gate accepts `macro.gold` 37h-fresh while a downstream consumer reads stale `prices."GC=F"`, gate PASS but downstream gets stale data → silent split-brain. Single-source gate = single truth.
