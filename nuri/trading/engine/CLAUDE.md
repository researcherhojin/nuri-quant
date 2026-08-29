# nuri/trading/engine/ — SIEGE Gated Execution

Implementation pointer for SIEGE v2 (3-D certification: Account × Asset Class × Execution Market). Canonical specs live elsewhere — this file documents only what's specific to this directory's implementation.

## Canonical references

- **Gate spec (full)** — `docs/CERTIFICATION_SPEC.md` — 11~30+ variable conditions, asset-class per-expansion logic, evidence tracking.
- **Canonical condition table** — `docs/STRATEGY.md §6` — base + per-asset-class conditions with grades + thresholds.
- **Confidence scoring formula** — `docs/STRATEGY.md §3.3`. Includes Learning-Memory `drift_multiplier`, conflict penalty, regime-fit, VIX gate composition. Phase 4 (safeslice — Wilson CI + witness cliff) replacement is queued; until then the formula in §3.3 is the live one. **Do not duplicate the formula here.**
- **Action-axis split** (`alpha_action` vs `portfolio_action`, PR A #429) — `nuri/core/axis.py` (helpers) + `docs/STRATEGY.md §3.7`. Engine emits both; concentration / sector / leverage violations route to `portfolio_action=REBALANCE` only — never urgent SELL.

## Engine-specific implementation notes

These are operational details unique to this directory; the canonical sources above own the rules themselves.

- **Gate policy lives in `config/rules.yaml siege_gates`** — code reads YAML, never hardcodes thresholds (§2.2).
- **v2 expansion**: gates `data_fresh` / `volatility_gate` / `external_data` group portfolio holdings by `asset_class` and apply per-class policy from `siege_gates.asset_classes.<class>`. Result: `total_conditions` is **11–30+ variable** depending on portfolio composition. A mixed US + KR + ETF portfolio expands to ~23 conditions; an empty / unconfigured portfolio falls back to legacy SPY/VIX single-check.
- **Severity at a glance** — useful when triaging a `certify()` failure without bouncing to STRATEGY §6: error-grade gates are `position_limit` / `sector_limit` / `stop_loss_growth` / `stop_loss_value` / `leverage_ban` (any single fail → REJECTED). Warning-grade gates (do not reject, surface only) are `data_fresh` / `volatility_gate` / `external_data` / `conflict_free` / `drift_safe` / `macro_event_alignment`. Full table with per-class thresholds: `docs/STRATEGY.md §6`.
- **Account-strategy injection**: `account_strategies.<strategy>` keys read per account are `stop_loss` (`_check_stop_loss_compliance`) and `max_single_position` (`_check_position_limits`). `_check_sector_limits` uses the global `MAX_SECTOR_EXPOSURE` only — per-account `max_sector_exposure` is deferred until the portfolio simulator (E3-4, see `config/rules.yaml` comment). Strategy is determined by the holding's `account` column joined with `portfolio.yaml accounts.<account>.strategy`.
- **입력이 없는 게이트는 FAIL(warning) 이지 PASS 가 아니다** — `_check_volatility_for_class` 는 지표가 없으면 `passed=True, "데이터 없음 — 스킵"` 을 냈다. config 가 선언한 `kospi` / `yield` 는 **`macro` 에 0행**(2026-08-10 프로덕션 실측) → `volatility_gate_kr_index` · `volatility_gate_bond` 가 도입(#248) 이래 **한 번도 평가되지 않은 채 매 인증서에 초록**이었다. ⚠️ 미수집이 아니다 — `prices.KOSPI` 419행 / `prices.TLT` 46행이 있고 **같은 인증서의 freshness 게이트가 이미 그걸 읽는다**. 변동성 쪽만 `_get_indicator_value` → `macro` 전용이라 못 본다. 두 테이블을 오가는 게이트를 새로 짤 땐 입력이 어느 테이블에 떨어지는지 먼저 확인할 것. **#1032 에서 `kospi` 는 `_PRICES_BACKED` 명시 매핑으로 해소** — 블랭킷 폴백(이름 대문자화)은 엉뚱한 티커로 조용히 해석돼 게이트가 **다른 시계열로 통과**할 수 있어 쓰지 않는다. `yield`(bond) 도 **#1020 에서 해소** — allowlist 는 이제 비었다. 포인터만 `us_10y_yield` 로 옮기는 것으로는 부족했다: `_compute_3d_change` 는 **상대 %** 라 같은 14bp 이동이 금리 1% 에서 14%, 4.7% 에서 3% 로 읽혀 임계값 의미가 레짐마다 변한다. 프로덕션 실측(2021~2026, n=1,246)에서 3일 변화 p95 가 상대로는 10.53%→3.11% 로 무너지는데(평균 금리 1.48%→4.38%) 절대로는 15→13bp 로 안정적이었고, 상대 5년 pooled p95(6.9%)로 잡았다면 2021 년 16 회·2022 년 35 회 발화하다 **2026 년 0 회** 였다. 그래서 `_compute_3d_bp` 를 새로 두고 `us_10y_yield_3d_bp > 20bp` 로 갔다(연도별 발화 1/32/22/12/6/1, 전체 5.9% — 형제 게이트 equity_us 5.1%·commodity 2.3%·fx 1.1% 대역). **금리에는 상대 %, 가격에는 절대값을 쓰지 말 것** — 새 computed 형태를 추가할 땐 `_COMPUTED_SUFFIXES` 가 단일 출처이며 계약 테스트가 거기서 접미사를 읽는다(손으로 복사하면 새 형태를 dangling 으로 오탐한다).
  **Test:** `tests/trading/engine/test_volatility_gate_contract.py::TestBondGateUsesAbsoluteBasisPoints` — 뮤테이션 3종(`_compute_3d_bp` 를 상대 % 로 · config 를 `_3d_change` 로 · config 를 원래 dangling 으로) 전부 FAIL 실측. 카나리아 `test_relative_change_would_have_diverged` 가 두 단위가 실제로 갈리는지 먼저 확인해 단위 단언이 공허해지지 않게 한다. 30줄 위 `_check_freshness_for_class` 는 처음부터 `age is None → passed=False` 라, 같은 파일 두 게이트가 같은 상황에 반대로 답하고 있었다. semantics 를 고쳐도 **다음 dangling 포인터는 못 막으므로**, config 선언을 수집기 레지스트리(`collectors/macro.py` 의 `FRED_SERIES` / `YFINANCE_SYMBOLS`)와 대조하는 계약을 따로 건다 — allowlist 는 `test_cross_stage_imports.py` 와 같은 양방향(새 dangling 도, 해소 후 방치된 항목도 FAIL). 새 asset class 를 추가하면 지표 수집 여부를 먼저 확인할 것. STRATEGY §2.6 "게이트 입력이 없을 때" 의 SIEGE 적용 사례.
  **Test:** `tests/trading/engine/test_volatility_gate_contract.py::TestUnknownIndicatorFailsTheGate::test_missing_primary_fails_as_warning` (semantics) + `::TestVolatilityGateContract::test_every_declared_indicator_is_collected_or_allowlisted` (계약) — 뮤테이션 4종(per-class PASS 복귀 · legacy VIX PASS 복귀 · 새 dangling 포인터 · stale allowlist) 전부 FAIL 실측.
- **Evidence record per gate** — every condition produces `(source, value, threshold, policy_ref)` for OAE traceability and persistence into the `certifications` table (E4-0a, PR #410).
- **Snapshot invariant**: `CertSnapshot` ContextVar threads `(regime, portfolio_df, portfolio_raw, portfolio_hash, portfolio_error)` through all gate internals — single DB read derives the hash that all downstream consumers see. Any new gate must read from the snapshot, not re-fetch.
  ⚠️ **스냅샷 접근자의 fallback 도 `db_path` 를 받아야 한다.** `_snapshot_portfolio()` / `_current_regime()` / `_snapshot_portfolio_raw()` 는 스냅샷이 없으면 fresh DB read 로 떨어지는데, 앞의 둘만 `db_path` 를 안 받아서 `_check_position_limits(db_path=X)` 같은 직접 호출이 기본 DB 를 읽었다(#1052). **이 결함은 기존 테스트로 보이지 않는다** — `certify()` 안에서는 ContextVar 가 DB 읽기를 통째로 건너뛰어 그 배선이 dead code 이기 때문에, 배선 6곳을 되돌려도 `tests/trading/engine` + `tests/llm` 611개가 초록이었다(2026-08-14 실측). 게이트를 **스냅샷 밖에서** 직접 부르는 테스트만 이걸 잡는다.
  **Test:** `tests/trading/engine/test_certify_db_path_isolation.py::TestGatesReadOnlyTheGivenDbOutsideCertify` — 배선을 되돌리면 8개 중 4개 FAIL. 구조 쪽 짝은 `tests/core/test_db_path_forwarding.py`.

## 논지 verdict 롤업 (`thesis_criteria.py`, #1096)

`theses.verdict` 의 **유일한 writer** 다. 값은 전부 `thesis_criteria_checks` 에서 나오며 손
라벨링이 아니다. 우선순위: 반증(마감 무관) → 철회/교체(`abandoned`) → 마감 미도달(판정 보류)
→ 전 기준 측정됨(`held`) / 아니면 `unevaluable`. **부분 측정은 `held` 가 아니다** — #1092 가
기준 층에서 잠근 "`unevaluable` 은 `holding` 이 아니다" 의 논지 층 대응물이다.

⚠️ **빈 컬렉션에 `all()` 을 쓰면 공허참으로 만점이 나온다.** 기준 0건인 논지가
`all([]) is True` 로 `held` 를 받았다. 도달하지 않았던 건 롤업 쿼리가 INNER JOIN 이어서지
방어가 있어서가 아니었고, LEFT JOIN 뮤테이션은 테스트를 전부 초록으로 통과했다. 채점·게이트에
`all(...)` 을 쓸 땐 빈 입력을 **먼저** 걷어낼 것.
⚠️ **효력을 가진 적 없는 논지는 채점 대상이 아니다.** `draft` 와 `effective_date` 가 미래인
논지가 verdict 를 받고 있었다 — 특히 9월 발효 논지가 5월부터 판정이 쌓여 **유효해지기도 전에
`broken`** 이 됐다(Codex 리뷰 2026-08-18 재현). 근본 원인은 롤업이 아니라 `run_daily_checks`
가 `effective_date` 를 안 본 것이라 두 곳을 같이 막는다.
**Test:** `::TestOnlyInForceThesesAreScored` — 필터 2개를 각각 지우면 FAIL, 카나리아
`test_the_same_thesis_is_scored_once_effective` 가 필터가 논지를 영영 묻지 않는지 확인한다.

**Test:** `tests/trading/engine/test_thesis_verdict.py::TestInProgressStaysBlank::test_zero_criteria_is_not_a_vacuous_pass`
— 가드를 지우면 FAIL. 나머지 규칙은 같은 파일에서 뮤테이션 9종(측정 완결성 · 철회 · 우선순위 ·
마감 없음 · machine 손판정 · 사람판정 덮어쓰기 · 자리표시자 · 스케줄러 배선 · 공허참) 전부 FAIL 실측.

## Execution Priority

Mechanical ordering when emitting actions: `stop_loss → take_profit → trailing_stop_set → new_buy`.
- Within `stop_loss`: sort by `loss%` descending (biggest loss first — bleeding stops first).
- Within `take_profit`: sort by `excess%` descending (biggest winner first — lock in gains).
- Rationale: declining momentum loses more per hour delayed; rising momentum is more forgiving.
- ⚠️ **이 순서는 코드에 없다 (2026-08-02 감사).** `config/rules.yaml execution_priority` 는 어느 모듈도 읽지 않고(`order` / `stop_loss_sort` / `take_profit_sort` 전부 소비처 0), 이 문서가 "Codified in config" 라고 적어둔 탓에 배선된 것으로 읽혀 왔다. 위 서술은 **설계 의도**이지 현재 동작이 아니다. 실제로 순서를 강제하려면 소비자를 만들어야 하고 그건 매매 동작 변경이라 STRATEGY PR 대상.

## regime 어휘 — canonical 이거나 NULL (#1268)

`decisions.regime` 은 `ALL_REGIMES` 10개 값 또는 NULL 만 담는다. `_snapshot_market_context`
가 regime 을 채우는 **두 경로**(`pipeline_events` payload · `classify_regime()` fallback)
합류 지점에서 `canonical_regime_or_none` 으로 한 번 정규화한다 — 경로마다 붙이지 않는 이유는
새 경로가 생겨도 자동으로 덮이기 때문이다.

payload 경로가 더 위험하다: **다른 생산자가 쓴 임의 JSON** 이라, `#832` 가 이 가드를 만든
바로 그 free-text 유입 경로다 (`recommendations.regime` 에 `''` · `'[recovery] 비중 축소'`
가 실제로 남아 있다).

⚠️ **거부는 NULL 이고, NULL 은 `decisions_context` freshness 를 건드린다** (#1267, warn 24h /
fail 60h). 의도한 것이다 — 어휘 밖 라벨을 조용히 저장하는 것보다 라벨 부재가 보이는 편이 낫다.

⚠️ **"모든 regime writer 에 가드" 는 틀린 원칙이다.** `candidate_runs.regime` 은
`UNKNOWN_REGIME`("unknown", 의도적으로 `ALL_REGIMES` 밖)을 정당하게 저장한다. 대상은
**어휘가 `ALL_REGIMES` 인 컬럼**뿐이다.

`certifications.regime` 도 같은 규약이다 (#1293). 가드는 `_classify_regime_fresh` 에 있는데,
그 함수가 **두 경로의 유일한 합류점**이기 때문이다 — `CertSnapshot.regime`(`_build_snapshot`)
도, snapshot 밖 `_current_regime()` 도 여기서 값을 받는다. `decisions.py` 와 같은 배치 원칙.

이쪽이 셋 중 위험이 가장 컸다: 행수가 `decisions` 의 12배(4,525)이고, 값이
`_check_regime_overrides` 의 `RULES...regime_overrides.get(regime, {})` 로 간다 —
`.get` 은 어휘 밖 키에 예외도 경고도 없이 **기본값**을 준다. writer 가 유일한 방어선이다.

⚠️ **이 파일의 다른 테스트들처럼 `_classify_regime_fresh` 를 mock 하면 가드를 건너뛴다.**
가드를 검증하려면 그 **안쪽**(`classify_regime`)을 mock 할 것.
**Test:** `tests/trading/engine/test_certification_persist.py::TestSnapshotInvariant::test_free_text_regime_is_persisted_as_null`
(+ `::test_every_canonical_regime_survives` 대조군 — 없으면 `return None` 구현도 통과한다).

`certifications.regime` 은 아직 무가드다 — 행수가 12배이고 값이 `.get(regime, {})` 로 가서
성격이 달라 **#1293** 으로 분리했다.

**Test:** `tests/trading/engine/test_regime_canonical_guard.py` — 어휘 밖 7종 거부 + canonical
10종 전부 보존(대조군) + writer 대칭 AST 스윕 + known-gap 양방향.
