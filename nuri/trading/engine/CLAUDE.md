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
- **입력이 없는 게이트는 FAIL(warning) 이지 PASS 가 아니다** — `_check_volatility_for_class` 는 지표가 없으면 `passed=True, "데이터 없음 — 스킵"` 을 냈다. config 가 선언한 `kospi` / `yield` 는 **`macro` 에 0행**(2026-08-10 프로덕션 실측) → `volatility_gate_kr_index` · `volatility_gate_bond` 가 도입(#248) 이래 **한 번도 평가되지 않은 채 매 인증서에 초록**이었다. ⚠️ 미수집이 아니다 — `prices.KOSPI` 419행 / `prices.TLT` 46행이 있고 **같은 인증서의 freshness 게이트가 이미 그걸 읽는다**. 변동성 쪽만 `_get_indicator_value` → `macro` 전용이라 못 본다. 두 테이블을 오가는 게이트를 새로 짤 땐 입력이 어느 테이블에 떨어지는지 먼저 확인할 것. **#1032 에서 `kospi` 는 `_PRICES_BACKED` 명시 매핑으로 해소** — 블랭킷 폴백(이름 대문자화)은 엉뚱한 티커로 조용히 해석돼 게이트가 **다른 시계열로 통과**할 수 있어 쓰지 않는다. `yield`(bond) 는 threshold 단위 문제라 아직 allowlist 에 남아 있다(#1020). 30줄 위 `_check_freshness_for_class` 는 처음부터 `age is None → passed=False` 라, 같은 파일 두 게이트가 같은 상황에 반대로 답하고 있었다. semantics 를 고쳐도 **다음 dangling 포인터는 못 막으므로**, config 선언을 수집기 레지스트리(`collectors/macro.py` 의 `FRED_SERIES` / `YFINANCE_SYMBOLS`)와 대조하는 계약을 따로 건다 — allowlist 는 `test_cross_stage_imports.py` 와 같은 양방향(새 dangling 도, 해소 후 방치된 항목도 FAIL). 새 asset class 를 추가하면 지표 수집 여부를 먼저 확인할 것. STRATEGY §2.6 "게이트 입력이 없을 때" 의 SIEGE 적용 사례.
  **Test:** `tests/trading/engine/test_volatility_gate_contract.py::TestUnknownIndicatorFailsTheGate::test_missing_primary_fails_as_warning` (semantics) + `::TestVolatilityGateContract::test_every_declared_indicator_is_collected_or_allowlisted` (계약) — 뮤테이션 4종(per-class PASS 복귀 · legacy VIX PASS 복귀 · 새 dangling 포인터 · stale allowlist) 전부 FAIL 실측.
- **Evidence record per gate** — every condition produces `(source, value, threshold, policy_ref)` for OAE traceability and persistence into the `certifications` table (E4-0a, PR #410).
- **Snapshot invariant**: `CertSnapshot` ContextVar threads `(regime, portfolio_df, portfolio_raw, portfolio_hash, portfolio_error)` through all gate internals — single DB read derives the hash that all downstream consumers see. Any new gate must read from the snapshot, not re-fetch.
  ⚠️ **스냅샷 접근자의 fallback 도 `db_path` 를 받아야 한다.** `_snapshot_portfolio()` / `_current_regime()` / `_snapshot_portfolio_raw()` 는 스냅샷이 없으면 fresh DB read 로 떨어지는데, 앞의 둘만 `db_path` 를 안 받아서 `_check_position_limits(db_path=X)` 같은 직접 호출이 기본 DB 를 읽었다(#1052). **이 결함은 기존 테스트로 보이지 않는다** — `certify()` 안에서는 ContextVar 가 DB 읽기를 통째로 건너뛰어 그 배선이 dead code 이기 때문에, 배선 6곳을 되돌려도 `tests/trading/engine` + `tests/llm` 611개가 초록이었다(2026-08-14 실측). 게이트를 **스냅샷 밖에서** 직접 부르는 테스트만 이걸 잡는다.
  **Test:** `tests/trading/engine/test_certify_db_path_isolation.py::TestGatesReadOnlyTheGivenDbOutsideCertify` — 배선을 되돌리면 8개 중 4개 FAIL. 구조 쪽 짝은 `tests/core/test_db_path_forwarding.py`.

## Execution Priority

Mechanical ordering when emitting actions: `stop_loss → take_profit → trailing_stop_set → new_buy`.
- Within `stop_loss`: sort by `loss%` descending (biggest loss first — bleeding stops first).
- Within `take_profit`: sort by `excess%` descending (biggest winner first — lock in gains).
- Rationale: declining momentum loses more per hour delayed; rising momentum is more forgiving.
- ⚠️ **이 순서는 코드에 없다 (2026-08-02 감사).** `config/rules.yaml execution_priority` 는 어느 모듈도 읽지 않고(`order` / `stop_loss_sort` / `take_profit_sort` 전부 소비처 0), 이 문서가 "Codified in config" 라고 적어둔 탓에 배선된 것으로 읽혀 왔다. 위 서술은 **설계 의도**이지 현재 동작이 아니다. 실제로 순서를 강제하려면 소비자를 만들어야 하고 그건 매매 동작 변경이라 STRATEGY PR 대상.
