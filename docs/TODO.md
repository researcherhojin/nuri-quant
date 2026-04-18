# Nuri-Quant — Work Backlog

이 문서는 **앞으로 할 일**만 기록한다. 완료된 항목은 git log + closed PR + closed issue 가 진실 source. 새 작업을 시작하기 전에 이 순서를 확인하고, 새 발견은 GitHub 이슈로 등록한 뒤 이 표에 추가한다.

정책 (자동 매매 영구 deferred, 작업 규칙) 은 `docs/STRATEGY.md §7` 에 있다. 이 문서는 operational backlog 만 담는다.

---

## Tier 1 — 완료 (2026-04-13 ~ 04-15)

| # | 항목 | 이슈 | PR | 비고 |
|---|------|------|----|------|
| 1 | **i18n constants extraction** | [#226](https://github.com/researcherhojin/nuri-quant/issues/226) | #230, #231 | `lib/strings.ts` 에 ~145개 한국어 상수 추출. 19 파일 마이그레이션 완료. |
| 2 | **하네스 계층화** | — | #229 | Fowler Guide/Sensor 기반 구조화: CLAUDE.md 슬림 (511→238줄) + 7 scoped CLAUDE.md + AGENTS.md + 4 hooks |
| 3 | **티커 기반 First-Run 온보딩 UX** | [#133](https://github.com/researcherhojin/nuri-quant/issues/133) | #234, #235 | `/explore` 페이지 + 티커 검색/분석 API. 커버리지 보강 포함. |
| 4 | **연 배당금 / 배당 수익률 데이터** | [#227](https://github.com/researcherhojin/nuri-quant/issues/227) | #270 | `dividendRate` (연 배당금 USD) + `dividend_yield_pct` (백분율) 컬럼 추가. fundamentals 테이블 마이그레이션 18-19. 2026-04-14 머지. |
| 5 | **Universe + Agent Data Coverage 통합 (P0)** | [#272](https://github.com/researcherhojin/nuri-quant/issues/272) | #275-#286 (12 PRs) | Audit에서 발견한 데이터 사일로 (fundamentals 2%) + universe label drift 해결. fundamentals 99%, prices 99%, KOSPI 200 100% 달성. 자동 검증 게이트 추가. |
| 5a | ↳ Phase 2a `universe_sync` | — | #276 | Wikipedia S&P 500 fetch + KRX/FDR KOSPI 200 fetch, manual ETF 보호 |
| 5b | ↳ Phase 2b BaseCollector `--source` | — | #278 | portfolio/universe/all 모드. 9 collectors tqdm + N/A coverage 진단 |
| 5c | ↳ Phase 2c validate_universe + CI | — | #284, #286 | 7-check coverage gate, warning-only CI job |
| 5d | ↳ KR/yfinance 성능 + UX fix | — | #281, #283, #285 | KR collect 33초, yfinance 10-thread parallel, sequential delay |
| 6 | **Privacy scanner ticker+PnL pattern** | — | #289 | STRATEGY §4.4.1 ticker+PnL 사각지대 보완. `-NN% (SYMBOL)` 괄호형 + `SYMBOL ±NN%` 인접형 양 패턴 감지 (예시는 `docs/STRATEGY.md §4.4.1` 참조), `origin/main..HEAD` unpushed commit message 스캔 추가, `TICKER_FALSE_POSITIVES` 120개. PR #202 class 차단. |
| 7 | **Shell scripts 전수 shellcheck clean** | — | #290 | 16개 `.sh` (1,504 lines) → shellcheck 0 issues. `set -euo pipefail`, shebang 통일, 실제 버그 fix (trap SC2064, read -r, RSYNC_OPTS array), `make lint-sh` + CI job 추가 |
| 8 | **OpenAI gpt-5.4-nano LLM 리포트 (STRATEGY §4.4.3 Tier 2)** | — | #294 | Ollama 휴면 → OpenAI primary. STRATEGY §4.4.3 정책 개정 (Tier 2 + ZDR 필수). `chat_text()` + `OPENAI_ZDR_APPROVED` 게이트. fallback chain (OpenAI → llama.cpp → Ollama). **부수 fix**: flaky `test_collect_full_flow` `df.copy()` (#295), security-scan 5m→10m timeout, codecov/patch 커버리지 테스트 3개 보강 |
| 9 | **uv sync 충돌 해결 (fastapi <0.129 pin)** | [#277](https://github.com/researcherhojin/nuri-quant/issues/277) | #291 | openbb-core ↔ fastapi version conflict 해결. dependabot ignore 추가 |
| 10 | **KR `n/a (US-only)` 표시 개선** | — | #288 | US_ONLY_TABLES frozenset + `check_universe_coverage.py` + `validate_universe.py` detail. 수집 실패 vs 소스 한계 시각 구분 |
| 11 | **#272 Phase 3 (Eval): validate_universe + US_ONLY 회귀 테스트** | — | #296 | 20 tests: TestUsOnlyTables(4) + TestRunValidation/Print/Main/Fetch(11) + TestOutputFormat(5) |
| 12 | **#272 Phase 4 (UX): Dashboard coverage widget + `/api/coverage`** | — | #297 | `CoverageStatus` widget (5/5 PASS 헤더 + 5-col 테이블 + 소스 한계 footer). 14 tests (backend 5 + frontend 9) |
| 13 | **README drift sync** | — | #309 | collectors 24→26, LLM 우선순위 (OpenAI primary), test counts 2,763→2,934. Codex APPROVED. |
| 14 | **B2 — Learning Memory outcome read 역방향** | — | #310 | `_compute_weights` SELECT 에 `outcome_30d` 누락 + `sqlite3.Row.get()` 없음. 두 층 버그로 수개월간 weight 역방향. Fix + 3 regression (revert-proof). #308 lock-in 해제. |
| 15 | **B1 — recommendations UNIQUE + UPSERT** | — | #311 | `UNIQUE(date, ticker, action)` → `UNIQUE(date, ticker)`. Migration 20 (MAX(id) dedup). `INSERT OR REPLACE` → `ON CONFLICT DO UPDATE` (id 보존 — `trades.recommendation_id` FK 안전). 프로덕션 20 중복 그룹 정리. |
| 16 | **#248 SIEGE v2 Phase 1 — asset-class gates** | [#248](https://github.com/researcherhojin/nuri-quant/issues/248) | #312 | Gate 5/7/8 per-asset-class (us/kr_equity/kr_index/commodity/bond). Cross-market spillover (KOSPI+SPY, USD/KRW+VIX). `config/rules.yaml siege_gates` spec. Codex challenge (3 결함 지적) → 재설계 → APPROVED. |
| 17 | **#89 인터랙티브 백테스트 sliders + live equity curve** | [#89](https://github.com/researcherhojin/nuri-quant/issues/89) | #332 | `run_interactive_backtest()` — regime change arm, stop/tp threshold hit 시 disarm. `/swing/backtest/equity` 가 `sma`/`period`/`sl`/`tp` 쿼리 수락 + 5분 TTL cache. UI 4-param sliders + URL deep-link (`/strategy?sma=100&lb=3Y&sl=-10&tp=30`) + static/interactive toggle. Tier 2 P1 #7 완료. |
| 18 | **wallstreet collect 성능 검증** | — | #285 | `make collect-universe` 에서 wallstreet 50min → 15min 41초 실측 확인 (universe 746). Tier 2 P2 #8 완료. |
| 19 | **Phase 2 A-1a — LM read path fix** | — | #361 | `_compute_weights` 가 `signals.verdicts` 대신 `agent_verdicts` 컬럼을 읽도록 수정. 133 rows silent fallback 해결. 5+3 regression (malformed JSON race, min_records parsed-gate, observability log level). Codex 2 round PASS. |
| 20 | **Phase 2 scheduler automation** | — | #363 | 스케줄러에 `consensus` job (07:05 KST) 추가. technical 07:00 완료 후, daily_report 08:00 전. LM input 데이터를 매일 자동 누적 → 2026-05-17± 첫 weight shift 예상. |
| 21 | **Phase 2 A-2a — consensus scoring_detail persist** | — | #364 | `save_to_recommendations` 의 hardcoded `scoring_detail=None` 제거. `_build_consensus` 가 per-agent weight × confidence contribution breakdown 계산, JSON 직렬화해 persist. Schema: `source`/`schema_version` discriminator + `basis_action` + `final_action_source` (weighted_sum/risk_veto/divergence_penalty). A-2b/c 가 consume 할 contract 완성. Codex 2 round (HIGH/MEDIUM/LOW + 1 residual gap → 모두 fix). |
| 22 | **Phase 2 A-2b-pre — candidates discriminator + VIX sync** | — | #366 | A-2a Round 2 follow-up. candidates.py scoring_detail 에 `source="candidate"` + `schema_version=1` 추가 (consensus 와 구분). VIX blocked/caution 경로에서 `scoring_detail["final_confidence"]` + `vix_penalty` 업데이트 — `c.confidence` 와 audit trail stale 방지. tracker.py falsy guard → `is not None` (empty dict `{}` persist). 4 regression lock. Codex 2 round (Medium VIX fix + Round 2 no findings). |
| 23 | **Phase 2 A-2b — API expose scoring_detail + agent_verdicts** | — | #368 | 3 routes (`/consensus`, `/dashboard`, `/actions`) 에 scoring_detail + agent_verdicts pass-through. `_parse_json_field` helper + graceful NULL/malformed degrade. `_build_actions` 에서 urgent/check/hold bucket 전부 threading. Pylance pre-existing type error fix 포함. 8 regression test (consensus 2 + dashboard 2 + actions 3 + endpoint 1). Codex 2 round (HIGH `_build_actions` drop → fix, Round 2 no findings). CI Shard 1 `external_analysis` table 누락 mock fix 포함. |
| 24 | **Phase 2 A-2c — ConsensusTable scoring_detail UI** | — | #370 | `/consensus` 페이지에서 final_action_source 이모지 배지 (🛑 risk_veto / ⚠️ divergence_penalty) + basis_action ≠ final 시 "BUY → HOLD" 라벨 + expanded row agent card 에 weighted contribution % (`action_scores[basis_action]` 분모) + counted_for_basis_action emerald border. TS literal union (`Action`/`ScoringSource`/`FinalActionSource`) export + `SOURCE_META satisfies` 로 contract drift 방어. 7 regression lock. Codex 2 round (LOW 2건 causal share denominator + contract drift → fix, Round 2 LOW 1건 tooltip 수식 → fix). Live API 21 tickers verify. CI TS type-check fail (makeScoring mock 반환 string widen) → `Partial<ScoringDetail>` annotate fix. |
| 25 | **Phase 2 A-1b — rows_parsed gate tighten** | — | #372 | A-1a Round 2 residual P2 close. `_compute_weights` 가 HOLD-only row 를 `rows_parsed` 에서 제외 — 10 HOLD-only row 가 `min_records=10` gate 통과하던 silent fallback 차단. `rows_skipped_no_usable` 카운터 (codex 넓은 semantic: HOLD-only + 미등록 agent + 이상 action 값 포함). WARNING/INFO log 에 surface. 3 regression lock (fallback + anomaly INFO path). Codex 2 round (no blocking → 2 LOW rename + observability gap + Round 2 stale comment → 전부 fix). NEXT_SESSION drift 발견: agent_accuracy_snapshots job 이미 scheduler Sunday 08:00 등록돼 있음 — spec line stale. |
| 26 | **Phase 2 A-3 — unified sell-path stop_loss** | 2026-04-18 | #374 | 3 sell path (risk_agent / actions / certification) 가 각각 다른 threshold + operator 를 썼음 — risk_agent `STOCK_STOP_LOSS`(-7 global) + `<=`, actions 하드코딩 `< -7`, certification 만 per-account strategy + `<`. long_term(-20)/pension(-30) 계좌 보유 ticker 가 -7% 손실에서 잘못 urgent/breach 분류. Fix: `nuri/core/rules.py::get_stop_loss_for_account(account)` helper + callers 가 pnl 계산된 holding row 의 account 를 helper 에 전달 (codex Round 1 P1 aggregation mismatch 방지). Operator 도 `<` 로 통일 (codex P2). 15 regression test (helper 7 + risk_agent 4 + actions 4). Codex Round 1: P1 + P2 모두 fix. Round 2 hung → self-review debt (§4.3) + 다음 PR 에서 회수. 3016/3016 test-fast pass. |
| 27 | **chore(tooling) codex_review.sh wrapper** | 2026-04-18 | #376 | `scripts/codex_review.sh <pr> <round> "<prompt>"` — `codex exec` 래퍼 + 프롬프트/응답을 markdown 으로 archive. Raw rollout JSONL (`~/.codex/sessions/`) 은 canonical source, wrapper 는 PR-scoped human-readable excerpt. STRATEGY §4.3 debt recovery 용. gitignored. Shell Lint SC2320 ($? misuse) fix 포함. |
| 28 | **Phase 2 A-4 — catalyst requirement for non-emergency SELL** | 2026-04-18 | #377 | Non-breach SELL 이 "왜 지금?" 근거 없이 surface 되는 걸 차단. `nuri/core/catalyst.py::has_recent_catalyst(ticker)` — 14d ticker news OR 7d 유의미 macro_event (conf≥0.5, \|sent\|≥0.3). `candidates.py` 는 SELL + actionable 을 catalyst 없으면 `TIER_ADVISORY` 로 downgrade. `actions.py _build_actions` 는 non-breach SELL 을 catalyst 없으면 `hold` 로. **stop-loss breach 는 exempt** — §2.2 mechanical, `pnl < stop_loss_threshold` path 가 catalyst 호출 전에 early continue. §2.6 Soft penalty. **Bonus**: codex Round 1-2 debt recovery — risk_agent 의 `holding[0]` arbitrary row 를 per-row iterate + concentration sum-over-rows 로 수정. Round 3 clean. 14 new test. 3030/3030 pass. CI 3회 재시도 (Shell Lint / Doc Count / `has_recent_catalyst` unmocked). |
| 29 | **Phase 2 A-5 — intraday live oracle divergence flag** | 2026-04-18 | #379 | Stored `prices` 는 T-1 → 장중 recommendation 이 stale 값으로 판단 (NFLX 사례: stored $97.23 vs live $107.79, +10.87%). `nuri/core/live_price.py` — `fetch_live_price(ticker)` yfinance `fast_info.last_price` (시장외 / weekend / 예외 → None) + `check_divergence(ticker, stored, threshold=3.0)` `(is_divergent, pct, live)` 반환. `actions.py _build_actions` 는 per-item `live_price`/`divergence_pct`/`divergence_flag` + `⚠ 실시간 시세 divergence …` reason. **threshold 비교는 stored 사용 유지** — STRATEGY §2.6 Surface 단계. A-5b 에서 live 를 stop-loss/target 비교로 승격 예정. 22 new test (MarketHours 9 + Fetch 4 + CheckDiv 7 including exact-3% boundary + Actions integration 3). Codex Round 1: P2 (Mon 05:00 KST wrap-around bug — 전날 weekday 기반으로 판정) + LOW (operator `>` → `>=`). Round 2 CLEAN + docstring nit fix. |
| 30 | **Phase 2 A-6 — simplicity audit (actions aggregation + defensive getattr drop)** | 2026-04-18 | #381 | `_get_portfolio_map` 이 동일 ticker 의 여러 계좌 보유를 largest-position row 로 collapse 했던 것을 aggregation 으로 수정 — `position_pct` 합산, `pnl_pct`/`account` 는 worst-pnl row (A-4 codex Round 1-3 재발 flag close). Pension 계좌는 aggregation 에서 분리 (codex Round 1 P2 추가 fix — 혼합 ticker 에서 taxable slice 가 pension label 로 skip 되는 cross-contamination 방지). `Candidate.tier` dataclass default 이므로 4 call sites 의 `getattr(c, "tier", …)` 제거 + 7 MockCandidate 에 `tier` field 추가 — defensive lookup 이 test fixture 의 real-shape drift 를 숨기고 있었음. 6 regression (aggregation 4 + pension split 2). Codex 2 round CLEAN + pension fix. 3060/3060 pass. CI Privacy Leak Scan 한 번 fail — cSpell whitelist 에 broker name stems 추가했던 것이 scanner 에 잡혀 정확히 의도대로 차단 (§4.4.1), 해당 entries 제거하고 재push. |
| 31 | **E2 — Position-sizing theoretical foundation (Kelly/Markowitz/Faber + Symmetric amplifier + SIEGE limits hypothesis)** | 2026-04-18 | #391 | docs-only foundation for E3 regime-adaptive framework. STRATEGY §3.4 에 3 학술 인용 (Kelly 1956 framework + MacLean/Thorp/Ziemba 2011 fractional, Markowitz 1952 efficient frontier, Faber 2007 trend-following) — full bibliography + DOI. §2.6 Escalation Ladder 에 4번째 rung "Symmetric amplifier" (post-veto sizing, Hard veto always wins on conflict). §3.6 E3 placeholder + acceptance preview (baseline = current SIEGE, horizon = `outcome_30/60/90d`, asset-class benchmarks SPY/KOSPI/KRX300/GC=F, walk-forward 5Y/1Y, gates Sharpe+0.1 / Max DD ±5% / Monte Carlo). §3.7 SIEGE limits 진단 (live count `ALL_CERT_CHECKS` 11 base + per-class expansion, all downside-block — upside/opportunity-cost gate 0개) labeled hypothesis-grade. Sequencing: 사용자 페인 "보수적 결론" 의 구조적 원인은 sizing-rule legitimacy → 🅑→🅒→🅐 (codex Plan consult APPROVE: docs spike → framework → rebalance under new rules). Plan-stage codex consult 1 round (item #5 SIEGE_V2 "Future direction" cut, single source of truth STRATEGY §6/§3.7). Round 1 MODIFY (3 P1: Kelly source-claim mismatch, Markowitz overstrong, "16 conditions" 사실오류) + 4 lower (Faber bib, amplifier order, §3.7 prescriptive drift, E3 executability) → Round 2 APPROVE. 3060/3060 test-fast. Archive: `codex-reviews/E2-round[1-2]-20260418-235007-*.md`. |

## Tier 2 — 다음 1 달 (P1)

**다음 세션 우선순위** — 구체적 작업 단위로 엄밀 정의 (2026-04-14 재평가).

| 우선 | # | 항목 | 이슈 | 카테고리 | 예상 | Acceptance |
|------|---|------|------|---------|------|------------|
| 🟡 P1 | 1 | **#272 Phase 5 (QA): Negative + Smoke run** | — | test | 1 세션 (네트워크 필요) | 빈 DB/yaml 삭제 negative 3건 + fresh clone → `make setup` → `make universe-sync-us/kr` → `make collect` → `validate_universe` 실행 기록 → `docs/SMOKE_RUN.md` 작성 |
| 🟡 P1 | 2 | **기술분석 통합 to 추천 파이프라인** | — | feat(recommend) | 1-2 세션 | JKHY 에피소드 (2026-04-14) 재발 방지. `nuri/quant/chart_analysis.py` (BB/MACD/RSI) 을 `candidates.py` / consensus에 자동 연동. "fundamentals Buy, technicals Sell" divergence 플래그 추가 |
| 🟡 P1 | 3 | **Universe weekly 1y backfill 자동화** | — | ops | 0.5 세션 | 실측 (2026-04-16): prices 99% 가 이미 3mo+ 보유 (원안 "5d only" 오독 정정). 진짜 gap 은 730/752 ticker 가 1-7일 stale — 기존 `stock_us_night/dawn/stock_kr` 이 `source="portfolio"` 기본값으로 돌아 universe-only ticker 수집 누락. Fix: scheduler 에 주 1회 `source="all"` + `period="1y"` backfill job 2 개 추가 (US/KR). `create_scheduler` 에 `kwargs=job.get("kwargs", {})` 한 줄 누락도 함께 fix. |
| ~~🟡 P1~~ | ~~4~~ | ~~**Earnings quality 분석 통합**~~ | — | ~~feat(recommend)~~ | ~~0.5 세션~~ | **Tier 3 research 로 이관** (2026-04-15). Codex challenge 로 (a) JKHY 실측 surprise 가 4-17% 정상 beat (HARNESS.md §2 에 기록된 "0.0~0.2% soft beat" 는 unit 오독에서 온 문서 오류), (b) literature (Bartov 2002, Kasznik & McNichols 2002, Neururer 2020) 는 meet/beat streak 을 **양의** 신호로 본다. 원안 spec 은 repo-wide unit inconsistency + mature large-cap false positive + literature 반대 방향 문제로 **기각**. 재설계는 Tier 3 "research note" 참조. |
| 🟢 P2 | 5 | **포트폴리오 온보딩 UI (YAML → Dashboard)** | [#25](https://github.com/researcherhojin/nuri-quant/issues/25) | feat(frontend) | 2-3 세션 | 수동 yaml 편집 제거. 2026-04-14 portfolio.yaml 수동 수정 페인포인트 직접 경험 |
| 🟢 P2 | 6 | **OpenBB 호환성 fix** | [#274](https://github.com/researcherhojin/nuri-quant/issues/274) | bug(collectors) | 1 세션 | openbb-core==1.6.7 ↔ openbb-news==1.6.1 충돌로 news/etf_flows 수집 불가. 점진적 upgrade 필요 (콜렉터별 smoke test 후 진행) |
| 🟢 P2 | 7 | **#272 Phase 2c-3 — universe-check 필수 게이트화** | — | ops | 10분 | `make collect-universe` 5/5 PASS 상태 유지 중 → 사용자 수동으로 branch protection required check 토글 |
| ⚪ P3 | 9 | **flaky test 일반 stabilization** | — | test | 1 세션 | #295는 resolved. 다른 flaky 후보 (parallel sys.modules 오염 패턴) 전수 감사 |
| 🟢 P2 | 10 | **Scheduler 로그 노이즈 감축** | — | chore(scheduler) | 0.5 세션 | 2026-04-18 Mac mini 첫 감사 발견. `data/logs/scheduler.err` 1.3MB/40hr (약 30MB/월) — 대부분 apscheduler INFO heartbeat. 3 개 tweak: (a) `logging.getLogger("yfinance").setLevel(logging.WARNING)` 로 401 Crumb / ETF fundamentals 404 같은 transient/expected 노이즈 suppress, (b) events collector 가 ETF ticker 에 대해 fundamentals 호출 skip (fundamental collector 의 ETF skip 패턴 복제 — VOO 404 재발 방지), (c) `RotatingFileHandler` 도입 (scheduler.err/log). 기능 영향 없음, 로그 가독성만 개선. Collector 자체는 정상 — ARK 도 3-tier fallback (cathiesark → ark-funds → yfinance) 으로 복구 확인됨. |

## Tier 3 — 다음 분기 (P2)

큰 작업. 선행 종속성 또는 외부 통합.

| # | 항목 | 이슈 | 카테고리 | 비고 |
|---|------|------|---------|------|
| 1 | **PR #202 commit message Stage 2 history cleanup** | — | security | 사용자 보유 종목 + 손실률이 PR #202 commit message에 노출되어 main git history에 박힘 (TEM/RKLB/PL 등 + PnL). STRATEGY §4.4.1 Stage 2 절차 (GitHub Support 또는 `git filter-repo`) 적용 결정 필요 |
| 2 | **Universe 추가 확장 (Russell 2000)** | — | feat(scanner) | 현재 419 (us_core 85 + us_sp500 254 + kospi200 80). 중소형주 발굴 위해 Russell 2000 (~2,000) 추가 검토 |
| 3 | **Meet/beat streak research spike** (Tier 2 P1 #4 에서 이관) | — | research | 아래 research note 참조 |

### Tier 3 — research note: meet/beat streak in revenue-backed growth

**기각된 원안**: `earnings_surprises` 기반 "soft beat" 플래그 (surprise < 2% 지속 3Q → 성장 stall 경고). FundamentalAgent score 에서 -1.

**기각 이유** (2026-04-15 codex challenge + 실데이터 audit):

1. **Unit 오독**: `docs/HARNESS.md §2` 에 기록된 "JKHY 4Q 연속 +0.0~0.2%" 는 저장 단위 오해. 실측 JKHY Q4'25~Q1'25 = 0.17 / 0.13 / 0.04 / 0.09 (decimal fraction) → **17% / 13% / 4% / 9% 실 beat** 이 맞음. 4-17% 전부 정상 beat 이고 soft beat 아님.
2. **Mature large-cap false positive**: threshold 2% 로 audit 결과 17 개 정상 mature 종목 (ECL, ETN, ABT, LIN, CTAS, CME 등) 이 trigger. Analyst coverage 정밀도 효과 ≠ 성장 stall.
3. **Literature 반대 방향**:
   - Bartov/Givoly/Hayn (2002): meet/beat = premium + 미래 성과 예측. <https://www.sciencedirect.com/science/article/abs/pii/S0165410102000459>
   - Kasznik & McNichols (2002): 꾸준한 meeter = valuation premium. <https://ideas.repec.org/a/bla/joares/v40y2002i3p727-759.html>
   - Neururer / Papadakis / Riedl (2020): 긴 streak = 낮은 ex ante uncertainty. <https://pubsonline.informs.org/doi/10.1287/mnsc.2019.3320>
4. **JKHY 실제 실패 모드**: falling knife (fundamentals 강 + technicals 약). P1 A3 divergence mechanical penalty 가 정확히 잡음 → soft-beat 탐지 불필요.

**Literature-backed pivot (Tier 3 research spec)**:

Neururer (2022) — meet/beat streak 은 **revenue-backed** 성장에서 양의 신호, **expense-backed** 에서는 warning. <https://www.sciencedirect.com/science/article/abs/pii/S106297692200103X>

Research acceptance:
- `earnings_surprises` cohort + 분기별 revenue_growth join
- Expense backing proxy 추가 (gross margin / operating margin trend)
- High-growth (revenue_growth ≥ 20%) universe 에만 적용
- Live universe 에서 backtest:
  - (a) streak 단독
  - (b) streak + revenue-backed filter
  - (c) streak + non-revenue-backed filter (expense engineering)
- Sector/regime 별 안정성 검증
- False positive 순 decision quality 향상 증명 필수

**승격 조건**: 백테스트에서 (b) 가 baseline 대비 +Sharpe/-drawdown 둘 다 유의미 + `pipeline_events` 샘플로 false-positive rate 를 validate 한 후에만 STRATEGY §2.6 Escalation Ladder 의 **Soft penalty** 레벨에 올림.

**참고**: 무작정 소환하지 말 것. 데이터 충분히 축적 (최소 2년 earnings + 4 분기 실시간 backtest) 이후 spike 로.

## 영구 배경 작업 (낮은 우선순위, 발견 시 처리)

| 항목 | 이슈 | 비고 |
|------|------|------|
| TestGate flake on push (PR-only pass) | [#85](https://github.com/researcherhojin/nuri-quant/issues/85) | classify_regime mock leak 수정 완료 (#188). 재발 시 추가 조사 |
| portfolio.yaml 데이터 정합성 모니터링 | — | 수동 매매 후 portfolio.yaml 동기화 필요. 평균가 drift 발견 시 즉시 교정 (사례: PR #204 세션에서 Sub RKLB avg \$60→\$87.7 발견) |
