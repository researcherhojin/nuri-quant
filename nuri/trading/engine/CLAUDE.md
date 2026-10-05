# nuri/trading/engine/ — Decision engine

What lives here after the SIEGE certification layer was retired (STRATEGY §6, #1619): the decision record (`decisions.py`, `record_decisions()` — the in-memory hand-off from the consensus job), the hard-veto and symmetric-amplifier gates (`gate.py`, `amplifier_gate.py`, STRATEGY §2.6), BUY/SELL conflict detection (`conflicts.py`), learning memory (`memory.py`) and the thesis verdict roll-up (`thesis_criteria.py`). Canonical specs live elsewhere — this file documents only what is specific to this directory's implementation.

## Canonical references

- **Confidence scoring formula** — `docs/STRATEGY.md §3.3`. Includes Learning-Memory `drift_multiplier`, conflict penalty, regime-fit, VIX gate composition. Phase 4 (safeslice — Wilson CI + witness cliff) replacement is queued; until then the formula in §3.3 is the live one. **Do not duplicate the formula here.**
- **Action-axis split** (`alpha_action` vs `portfolio_action`, PR A #429) — `nuri/core/axis.py` (helpers) + `docs/STRATEGY.md §3.7`. Concentration / sector / leverage violations (surfaced from `rebalance_advisor` since #1619, §6 처분표) route to `portfolio_action=REBALANCE` only — never urgent SELL.

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
**Test:** `tests/trading/engine/test_thesis_verdict.py::TestOnlyInForceThesesAreScored` — 필터 2개를 각각 지우면 FAIL, 카나리아
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

`certifications.regime` 은 #1293 에서 같은 가드를 받았다가 writer(`certification.py`)가 #1619 로 삭제돼 지금은 쓰는 코드가 없다 — `tests/trading/engine/test_regime_column_vocabulary.py` 가 `unwritten` 으로 분류하고 writer 부재를 잠근다.

**Test:** `tests/trading/engine/test_regime_canonical_guard.py` — 어휘 밖 7종 거부 + canonical
10종 전부 보존(대조군) + writer 대칭 AST 스윕 + known-gap 양방향.
