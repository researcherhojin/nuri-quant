# SPEC: Phase 2c — `validate_universe.py` + CI Coverage Gate

**Issue**: [#272](https://github.com/researcherhojin/nuri-quant/issues/272)
**Phase**: 2c (Eval / CI gate)
**Author**: 2026-04-14
**Status**: **Shipped** 2026-04-15 — spec PR #280 · impl PR #284 · CI gate PR #286 (all merged). Retained for historical reference.
**Depends on**: PR #276 (Phase 2a, merged), PR #278 (Phase 2b, merged)
**Parent spec**: docs/SPEC_universe_agent_coverage.md §3.3

---

## 1. 목적

PR #276/#278에서 universe 정의 + collector universe 모드를 구축했다. 이제 **자동 검증**이 필요:

- universe.yaml이 upstream (Wikipedia/KRX)과 동기화 유지되는가?
- collector가 실제로 universe 종목 데이터를 채워 넣었는가?
- 둘 다 만족하지 못하면 **CI에서 fail** → main 머지 차단

이게 없으면 Phase 2a/2b 인프라가 의미 없음 (silent drift 가능).

---

## 2. Acceptance Criteria

### 2.1 universe.yaml 일치율 (parent spec §2.1 재사용)

| 라벨 | 기준 source | 임계 |
|------|------------|------|
| `us_sp500_extended` ∪ `us_core` | Wikipedia 503종목 | ≥ **95%** (≥ 478) |
| `kr_kospi200` | FDR top-200 by Marcap | ≥ **95%** (≥ 190) |

### 2.2 Agent data coverage (parent spec §2.2 재사용)

| 테이블 | 최소 coverage | 최대 stale |
|--------|--------------|-----------|
| `prices` | ≥ **95%** | 24h |
| `fundamentals` | ≥ **80%** | 7d |
| `analyst_ratings` | ≥ **70%** | 14d |
| `insider_trades` | ≥ **50%** | 30d |
| `superinvestors` | ≥ **80%** | 90d |

### 2.3 Per-check exit behavior

- All 7 checks PASS → exit 0
- ≥ 1 ERROR check fail → exit 1 (CI block)
- 모든 검사 결과 항상 출력 (단 1개 fail이라도 나머지 표시)

---

## 3. 구현 명세

### 3.1 `scripts/validate_universe.py`

**책임**: 7 check 순차 실행 → 결과 표 출력 → exit 0/1

**파이썬 API** (재사용 가능):
```python
def validate() -> dict[str, CheckResult]:
    """
    Returns:
        {check_name: CheckResult(status='PASS'|'FAIL', actual=float, threshold=float, ...)}
    """
```

**CLI**:
```bash
python scripts/validate_universe.py                  # 전체 (network fetch)
python scripts/validate_universe.py --no-fetch       # universe ↔ upstream skip (DB만)
python scripts/validate_universe.py --format json    # CI-parseable
python scripts/validate_universe.py --strict         # WARNING도 FAIL로 (기본 ERROR만 차단)
```

### 3.2 출력 형식

**Table mode (default, sys.stdout)**:
```
======================================================================
  Universe + Agent Coverage Validation (#272 Phase 2c)
======================================================================
  Check                            Actual    Threshold  Status
  ------------------------------------------------------------------
  universe.us_sp500                 100%      ≥95%       ✅ PASS
  universe.kr_kospi200              99%       ≥95%       ✅ PASS
  data.prices (US)                  97%       ≥95%       ✅ PASS
  data.fundamentals                 84%       ≥80%       ✅ PASS
  data.analyst_ratings              45%       ≥70%       🔴 FAIL
  data.insider_trades               52%       ≥50%       ✅ PASS
  data.superinvestors               96%       ≥80%       ✅ PASS

  Result: 6/7 PASS → exit 1 (1 ERROR check failed)
```

**JSON mode (CI)**:
```json
{
  "checks": [
    {"name": "universe.us_sp500", "actual": 1.00, "threshold": 0.95, "status": "PASS"},
    ...
  ],
  "summary": {"pass": 6, "fail": 1, "exit_code": 1}
}
```

### 3.3 CI integration

`.github/workflows/main-ci-cd.yml` 에 신규 job:
```yaml
universe-check:
  needs: detect-changes
  runs-on: ubuntu-latest
  if: needs.detect-changes.outputs.python == 'true'
  steps:
    - uses: actions/checkout@v4
    - name: Setup Python
      uses: actions/setup-python@v5
      with: { python-version: '3.12' }
    - name: Install deps
      run: uv sync --extra dev
    - name: Validate universe
      run: |
        python scripts/validate_universe.py --no-fetch --format json > result.json
        cat result.json
        # CI mode: --no-fetch (network 의존 차단), 결과만 검증
```

**중요 — 점진적 enforcement**:
- 초기 머지: warning만 (exit 0). Universe 데이터가 아직 채워지지 않음
- 사용자가 `make collect-universe` 실행 + 확인 후
- Branch protection 추가: `universe-check`를 required check로

→ 본 PR에는 CI job 추가만, "required" 설정은 사용자 조치 (별도)

### 3.4 Makefile

```makefile
validate-universe:        ## Universe + agent coverage 검증 (#272 Phase 2c)
	$(PYTHON) scripts/validate_universe.py

validate-universe-cache:  ## DB만 검사 (network fetch skip)
	$(PYTHON) scripts/validate_universe.py --no-fetch
```

---

## 4. 구현 파일 분해

| 파일 | 신규/수정 | 목적 |
|------|---------|------|
| `scripts/validate_universe.py` | 신규 | CLI + 7 check 로직 |
| `nuri/core/coverage.py` | 신규 | check 함수 (재사용 가능) |
| `Makefile` | 수정 | 2 타겟 추가 |
| `.github/workflows/main-ci-cd.yml` | 수정 | universe-check job |
| `tests/scripts/test_validate_universe.py` | 신규 | unit test (Phase 3) |
| `tests/integration/test_validate_universe_real.py` | 신규 | E2E with mocked DB |

**Coverage 계산 코드 위치**:
- 새 모듈 `nuri/core/coverage.py` — pure function, side-effect 없음
- `validate_universe.py`는 thin CLI wrapper

이게 좋은 이유:
- API에서도 사용 가능 (`/api/scan` 응답에 coverage 표시 — Phase 4)
- 단위 테스트 쉬움

---

## 5. 위험 + 완화

| Risk | Mitigation |
|------|-----------|
| 초기 데이터 부족 → CI 즉시 fail | Phase 2c 머지 직후엔 required check 미설정. `make collect-universe` 실행 후 enforce |
| Network 의존성 (Wikipedia/KRX 호출) | `--no-fetch` 모드로 CI 우회 |
| Stale check (last update 7d 등) | DB의 `updated_at` 컬럼 활용. 없으면 max(date) 사용 |
| `universe.yaml`에 manual extras (ARKK 등) → upstream에 없어도 PASS 유지 | safety: extras는 coverage 계산에서 제외 |

---

## 6. 단계적 enforcement 계획

| 단계 | 시점 | 동작 |
|------|------|------|
| 1 | 본 PR 머지 | CI job 추가 (warning only, exit 0) |
| 2 | `make collect-universe` 실행 후 (사용자) | 실제 coverage 측정 |
| 3 | 모든 check PASS 확인 후 | branch protection에 `universe-check` 추가 |
| 4 | 이후 | drift 감지 시 자동 차단 |

본 PR은 **단계 1만 다룸**. 단계 2-4는 사용자 조치.

---

## 7. PR 분할

| Sub-PR | 내용 | 추정 |
|--------|------|------|
| 2c-1 | `validate_universe.py` + `nuri/core/coverage.py` + 단위 테스트 | 0.5 세션 |
| 2c-2 | Makefile + CI workflow job | 0.25 세션 |
| 2c-3 (별도) | CI required check 활성화 + 문서 | 사용자 작업 |

본 spec은 2c-1 + 2c-2를 단일 PR로 묶는다 (≤3 commits).

---

## 8. Out of scope

- Phase 4 (UX) — `/api/scan` 응답에 coverage 추가는 Phase 4
- 자동 cron — universe-sync에 이미 있음 (Phase 2a)
- `superinvestors` table 자동 갱신 — 분기 1회면 충분, 별도 cron 불필요
- alert / Discord 통합 — Phase 4-5

---

## 9. Acceptance test plan

```bash
# 1. Spec 머지 후 (이 PR)
make validate-universe
# 기대: 7개 check 표시. 일부 FAIL 가능 (데이터 미수집), exit 0 (warn-only 모드 초기)

# 2. 사용자: make collect-universe
# (~10분, prices/fundamentals/wallstreet 채움)

# 3. 다시 validate
make validate-universe
# 기대: ≥6/7 PASS, exit 0

# 4. 의도적 fail 시뮬레이션
# 임시로 universe.yaml에서 100종목 제거 → validate → exit 1 검증

# 5. CI smoke
gh pr create  # → universe-check job 자동 실행 검증
```

---

## 10. Reference

- Parent spec: `docs/SPEC_universe_agent_coverage.md` §3.3
- 발견 세션: 2026-04-14 audit
- STRATEGY.md §2.1 (증거 우선), §5.7 (mechanical enforcement)
