# Nuri-Quant 전략 정의서

이 문서는 프로젝트의 존재 이유, 핵심 설계 결정의 근거, 개발 품질 기준을 정의한다. 새로운 기능을 만들거나 기존 구조를 변경할 때 이 문서의 원칙에 부합하는지 먼저 확인한다.

---

## 1. 왜 이 프로젝트를 만들었는가

**문제**: 개인 투자에서 감정과 직감에 의존하면 처분효과(Shefrin 1985)에 빠진다 — 수익 종목은 너무 빨리 팔고, 손실 종목은 너무 오래 잡는다.

**가설**: "왜 사야 하는지/팔아야 하는지"를 데이터로 증명하는 시스템을 만들면, 감정 개입을 제거하고 일관된 의사결정을 할 수 있다.

**핵심 차별점**: 추천을 내리는 것이 아니라, 추천의 근거를 증명하는 것이 목적이다.
- 20개 시그널 × 8,000+ 과거 트레이드 백테스트로 각 시그널의 승률/수익비(PF)를 검증
- 10개 에이전트가 독립적으로 분석한 뒤 가중 합의 (risk agent 거부권)
- SIEGE 10-gate가 모든 추천을 기계적으로 검증 — 1개라도 실패하면 REJECTED
- 5개 Plotly 차트가 최종 증거를 시각화

---

## 2. 설계 원칙

코드를 작성하거나 리뷰할 때 이 원칙을 적용한다.

### 2.1 증거 우선 (Evidence-first)

모든 BUY/SELL 판단에는 정량적 근거가 따라야 한다.

- 시그널 발생 → 해당 시그널의 레짐별 승률/PF 조회
- 에이전트 합의 → 각 에이전트의 판단 이유(reasoning) 기록
- 가격 타겟 → 매수가/손절가/익절가를 명시적 숫자로 제시
- **"좋아 보여서"는 이유가 아니다.** 숫자가 없으면 추천하지 않는다.

### 2.2 기계적 실행 (Mechanical execution)

규칙은 `config/rules.yaml`에 정의하고, 코드는 규칙을 실행만 한다.

- 손절 -7%(성장)/-10%(가치), 익절 +20%/+40%, 트레일링 -15% — 예외 없음
- VIX > 30이면 신규 매수 차단 — "이번엔 다르다"를 허용하지 않음
- SIEGE gate 통과 실패 → REJECTED. 수동 오버라이드 없음
- **규칙을 바꾸고 싶으면 YAML을 수정하고 백테스트로 검증한다. 코드에 예외 분기를 넣지 않는다.**

### 2.3 느슨한 결합 (Loose coupling via data)

파이프라인 8개 페이즈는 서로를 import하지 않는다. DB와 CSV를 통해서만 통신한다.

- **이유**: Phase C(Validate)를 다시 돌리면 Phase D(Classify)와 E(Recommend)가 자동으로 새 데이터를 사용한다. 직접 import하면 실행 순서와 상태 관리가 복잡해진다.
- **원칙**: 새 모듈을 추가할 때, 다른 페이즈의 함수를 직접 호출하지 않는다. DB 테이블이나 CSV를 통해 데이터를 전달한다.
- **예외**: 같은 페이즈 내부에서는 직접 import 허용 (예: `candidates.py`가 같은 페이즈의 `tracker.py` 사용).

### 2.4 관찰 가능성 (Observability)

시스템의 모든 상태 변화는 추적 가능해야 한다.

- `pipeline_events` 테이블: append-only event journal. `causation_id`로 이벤트 체인 추적.
- Freshness SLA: 각 데이터 소스별 warn/fail 임계값. PASS가 아니면 대시보드에 경고.
- SIEGE certification: 10개 조건의 pass/fail 결과가 매번 기록됨.
- **새 기능을 만들 때**: "이 기능이 실패하면 어떻게 알 수 있는가?"를 먼저 답하라.

### 2.5 비용 제로 (Zero-cost stack)

유료 API, 클라우드 서비스, 상용 소프트웨어에 의존하지 않는다.

| 선택 | 이유 |
|------|------|
| SQLite (not Postgres) | 별도 서버 불필요. WAL 모드로 동시 읽기. `tmp_path`로 테스트 격리. |
| Ollama (not OpenAI API) | 포트폴리오 데이터가 외부로 나가지 않음. API 비용 $0. 오프라인 가능. |
| OpenBB + yfinance (not Bloomberg) | 무료 데이터. OpenBB 추상화 → provider 교체 용이. yfinance는 폴백. |
| GitHub Actions (not Jenkins) | 오픈소스 무료 tier. lint + test + coverage + security 자동화. |

---

## 3. 핵심 아키텍처 결정 기록

향후 이 결정을 변경하려면, 아래 "이유"를 반박할 수 있는 근거가 필요하다.

### 3.1 DB가 유일한 통합 지점

`nuri/core/db.py`만 `sqlite3`를 import한다. 모든 다른 모듈은 `query()`, `query_df()`, `upsert_*()`, `get_db()`를 통해서만 DB에 접근한다.

**이유**: DB 접근 패턴을 한 곳에서 제어해야 WAL 모드 충돌 방지, 트랜잭션 관리, 마이그레이션이 안전하다. 또한 테스트에서 `db_path` 파라미터 주입으로 완전한 격리가 가능하다.

### 3.2 10-에이전트 가중 합의

10개 에이전트가 독립적으로 분석하고, 가중치 기반 투표로 합의한다.

**이유**: 단일 모델의 편향을 줄이기 위함. Risk agent에 거부권(SELL + confidence ≥ 80 → 전체 오버라이드)을 부여한 이유는, 손실 회피가 수익 추구보다 우선이기 때문이다.

**가중치**: `config/agents.yaml`에서 관리. Learning Memory가 과거 적중률을 추적하여 가중치를 ±30% 범위 내에서 동적 조정한다.

### 3.3 Confidence 스코어링 파이프라인

```
base = regime_win_rate × 60% + profit_factor × 40%
     × drift_multiplier (0.3 ~ 1.1)        ← Learning Memory
     × conflict_penalty (0.5x if high)      ← Conflict Detection
     × regime_fit_penalty (0.4x if avoid)    ← Strategy Map
     × position_penalty (0.3x if minimal)    ← Regime position sizing
     × vix_gate (0x if blocked, 0.5x caution)
```

**이유**: 단순 승률만으로는 부족하다. 현재 시장 레짐에서의 성과, 시그널 성능 변화(drift), 충돌 여부를 모두 반영해야 신뢰도 있는 점수가 나온다.

### 3.4 투자 규칙의 출처

모든 규칙에는 학술적/실증적 근거가 있다. 근거 없는 규칙은 추가하지 않는다.

| 규칙 | 근거 | 출처 |
|------|------|------|
| 손절 -7% | CAN SLIM 원칙 | O'Neil, *How to Make Money in Stocks* |
| 익절 +20%/+40% | 손익비 3:1 유지 | Minervini, *Trade Like a Stock Market Wizard* |
| 트레일링 -15% | 11년 백테스트 최적값 (73.9% 누적수익) | 자체 백테스트 |
| VIX > 30 매수 차단 | 공포 구간 승률 붕괴 검증 | 자체 시그널 백테스트 |
| 슈퍼투자자 ≥ 3명 | 13F 보유 종목의 초과수익 연구 | SEC EDGAR 분석 |
| 처분효과 경고 | 수익 종목 조기 매도 편향 | Shefrin & Statman, 1985 |

---

## 4. 개발 품질 기준

PR을 올리기 전 이 기준을 확인한다.

### 4.1 테스트

| 항목 | 기준 | 현재 |
|------|------|------|
| Backend tests | 고정 minimum 없음 — Codecov 1% relative regression gate (목표 ≥ 95%) | 2,253 tests, 91 files |
| Frontend tests | 목표 ≥ 90% | 593 tests, 45 files |
| E2E | 핵심 flow 커버 | 21 Playwright tests (4 spec) |
| CI 통과 | 필수 | lint + test + coverage + security |
| 네트워크 의존 | 금지 | conftest.py에서 yfinance/외부 API mock |

### 4.2 코드

| 항목 | 기준 |
|------|------|
| Linter | `ruff check` 통과 (E/F/W/I rules) |
| 커밋 메시지 | Conventional Commits 형식 (영문) |
| PR 단위 | 이슈 1개 = PR 1개, 커밋 3개 이하 |
| 새 규칙 추가 | `config/rules.yaml`에 정의, 코드에 하드코딩 금지 |
| 새 임계값 추가 | `config/agents.yaml`에 정의 |
| 시간 처리 | `kst_now()` / `today_kst()` 사용, `datetime.now()` 금지 |

### 4.3 데이터

| 항목 | 기준 |
|------|------|
| DB 접근 | `nuri/core/db.py` 함수만 사용 |
| 스키마 변경 | `_MIGRATIONS` 리스트에 추가, 직접 ALTER 금지 |
| 환율 | DB → OpenBB → `StaleExchangeRateError` (하드코딩 폴백 금지) |
| 외부 데이터 | 최소 10개 외부 소스 교차 확인 후 매매 판단 |

### 4.4 보안

| 항목 | 기준 |
|------|------|
| 시크릿 | `.env` 파일, git에 커밋 금지 |
| 인증 | DASHBOARD_PASSWORD 설정 시 HMAC-SHA256 keyed 토큰 기반 쿠키 인증 (Edge Runtime 호환, CodeQL js/insufficient-password-hash 대응) |
| CI | Trivy CRITICAL 취약점 → 머지 차단 |
| LLM | 포트폴리오 데이터 외부 전송 금지 (Ollama local only) |
| **개인 금융 데이터** | commit · PR · issue · 코드 주석 · 테스트 fixture · CI 로그에 절대 노출 금지. `config/portfolio.yaml`이 gitignored이지만 그 *내용*도 git 추적 대상에 들어가면 안 됨. broker 계좌명, 보유 수량, 평단가, 현금 잔고, 매매 이력 모두 해당. 자세한 룰은 아래. |

#### 4.4.1 개인 금융 데이터 enforcement (#138)

**권위 있는 차단 기준** — 문서가 아닌 시스템이 강제. `scripts/check_privacy_leak.py`에 정의된 패턴이 ground truth.

| 카테고리 | 차단 대상 | 허용 placeholder |
|---|---|---|
| Korean broker name | 카카오페이, 미래에셋, 키움증권, 삼성증권, NH투자증권, 토스증권, KB증권, 신한투자증권, 하나증권, 메리츠증권, 유안타증권, 대신증권, 이베스트투자증권, 흥국증권, IBK투자증권 | `Brokerage Alpha`, `Brokerage Beta`, `Brokerage Alpha Cash Account`, `Brokerage Alpha Securities` |
| Romanized broker | kakaopay, mirae, kiwoom, samsung_securities, nh_invest, toss_securities, shinhan_invest, hana_securities, meritz_securities (case-insensitive substring) | 동일 — 한글 placeholder를 영문 식별자로 변환 시 `brokerage_alpha` 등 사용 |
| Suspect monetary literal | 7자리 이상 정수 (`>= 1_000_000`) 가 동일 라인에 `total_invested`, `cash_balance`, `deposit`, `withdraw`, `principal`, `net_worth`, `buying_power` 키와 함께 존재 | round million 값 (`1_000_000`, `5_000_000`, …, `100_000_000`)은 placeholder로 자동 허용 |

**의도적 제외**:
- `한국투자증권` (KIS) 은 Open API 통합 대상으로 코드베이스에 합법적으로 등장 (`nuri/collectors/kis_*`, `docs/KIS_INTEGRATION.md`). 사용자 개인 KIS 계좌가 leak되는 경로는 `~/KIS/config/kis_devlp.yaml` (gitignored, 위치 자체가 repo 밖) — broker name 패턴이 아닌 credential file 패턴이 막아야 할 surface.

**방어 layer 3개** (defense in depth):
1. `scripts/check_privacy_leak.py` — 핵심 scanner. stdlib only, no deps.
2. `scripts/pre_push_check.sh` Section 4 — local pre-push gate. 로컬에서 실수 자동 차단.
3. `.github/workflows/main-ci-cd.yml` `privacy-scan` job — CI gate, 모든 PR에서 항상 실행 (frontend-only PR도 예외 없음). 머지 차단.

**새 broker name 추가 시**: `scripts/check_privacy_leak.py`의 `BROKER_NAMES_KO` / `BROKER_NAMES_EN` 튜플에 추가. 테스트는 `tests/test_check_privacy_leak.py`. 이 표도 같이 갱신.

**History cleanup (Stage 2 — 별도 작업)**:
이 enforcement는 main HEAD를 깨끗하게 유지. 그러나 leak이 처음 들어간 이전 commit(들)은 force push 또는 GitHub Support 요청 없이는 제거 불가. STRATEGY.md §5.4 (스코프 팽창) + CLAUDE.md (force push to main 금지)를 동시에 준수하기 위해 별도 작업으로 분리. 권장 순서: GitHub Support 요청 (비파괴) → 만족 못 하면 `git filter-repo` (사용자 명시 force-push 승인 필수).

---

## 5. LLM 에이전트 하네스 (Harness Engineering)

이 프로젝트는 LLM(Claude Code)이 주요 개발 도구다. LLM은 강력하지만 체계적으로 실패하는 패턴이 있다. 아래는 이 프로젝트에서 **실제로 겪은** 실패들과 그에 대한 방어 기제다.

### 5.1 할루시네이션 (Hallucination)

LLM은 존재하지 않는 함수, 파라미터, 파일 경로를 자신 있게 말한다.

**실제 사례:**
- `get_exchange_rate(db_path)` 호출 — 실제 시그니처는 `get_exchange_rate()` (파라미터 없음)
- `nuri.api.routes.dashboard.query` 패치 — 실제로는 `query`가 함수 내부에서 local import됨
- `MagicMock`을 `dataclasses.asdict()`에 전달 — 실제 dataclass 인스턴스가 필요

**방어:**
- 함수를 호출하기 전에 시그니처를 읽는다 (`grep -n "def function_name"`)
- 패치 대상이 모듈 레벨인지 local import인지 확인한다
- "아마 이럴 것이다"로 코드를 쓰지 않는다. 모르면 먼저 읽는다

### 5.2 확증 편향 (Context Length Bias)

컨텍스트가 길어지면 LLM은 이전에 자신이 한 말을 "맞다"고 가정하고, 실패를 같은 방식으로 반복 시도한다.

**실제 사례:**
- `daily_report` 테스트가 CI에서 3번 연속 실패. 매번 `runpy.run_module()`을 시도했으나, 근본 원인은 `generate_report()`가 같은 모듈에 정의되어 있어 runpy가 mock을 덮어쓰는 것. 3번째에서야 `main()` 직접 호출로 전환
- `runpy` + `monkeypatch.setattr()`로 `__main__` 블록 테스트 반복 실패. 원인: runpy는 모듈 소스를 새로 실행하므로 모든 이름이 재정의됨. 해결: `patch("source.module.function")`으로 소스 레벨 패치

**방어:**
- 같은 접근이 2번 실패하면 **접근 자체를 의심**한다. 3번째 시도는 금지
- 실패 시 "왜 실패했는가"를 먼저 진단한다. 에러 메시지를 읽고, 가정을 검증한다
- 긴 세션에서 `/compact` 후에도 이전 가정이 여전히 유효한지 코드를 다시 읽어 확인한다

### 5.3 유령 수정 (Phantom Fix)

LLM이 "수정했습니다"라고 말하지만, 실제로는 다른 곳을 고치거나 원래 문제가 해결되지 않은 상태.

**실제 사례:**
- Recharts mock 충돌: `coverage-push.test.tsx`의 `vi.mock("recharts")`가 `coverage-push-3.test.tsx`의 `price-chart` import를 깨뜨림. 원인은 vitest의 mock hoisting이 같은 워커의 모든 dynamic import에 영향을 미치기 때문
- OpenBB `obb.currency.price.historical` 패치 시도 — 모듈 레벨에 `obb`가 없어서 `AttributeError`. 실제로는 함수 내부 local import이므로 `patch.dict(sys.modules, {"openbb": mock_module})` 필요

**방어:**
- 수정 후 반드시 테스트를 실행한다. "논리적으로 맞을 것"을 신뢰하지 않는다
- 테스트가 통과하더라도 **의도한 라인이 실제로 커버되는지** coverage 리포트로 확인한다
- `vi.mock()` 사용 시 hoisting 영향 범위를 인식한다 (파일 단위, 워커 단위)

### 5.4 스코프 팽창 (Scope Creep)

LLM은 요청받은 것 이상을 "개선"하려는 경향이 있다.

**실제 사례:**
- #16에서 에이전트 3개 추가 요청 → config 외부화 + confidence 정규화 + 구조 수정 5건 + 프론트엔드까지 한 PR에 포함 (29파일, +2000줄)
- 커버리지 작업 중 발견한 "작은 버그"를 같은 PR에 수정하여 리뷰 범위 확대

**방어:**
- **이슈 1개 = PR 1개**. 선행 작업 발견 시 별도 이슈로 분리한다
- 커밋 3개 이하. 넘으면 스코프를 줄인다
- "이것도 같이 하면 좋겠다"는 하지 않는다. 별도 이슈를 만든다

### 5.5 테스트 환각 (Test Illusion)

테스트가 통과하지만 실제로는 타겟 코드를 실행하지 않는 경우.

**실제 사례:**
- `runpy.run_module()` + `patch("module.generate_llm_report_sync")`: runpy가 함수를 재정의하므로 mock이 무효화됨. 테스트는 실제 Ollama에 연결 시도 → 300초 timeout 후 실패
- `if editBtns.length > 0` 가드로 감싼 테스트: 버튼이 렌더링되지 않으면 테스트 로직이 아예 실행되지 않지만 테스트는 통과

**방어:**
- 커버리지 리포트에서 **의도한 라인 번호가 실제로 커버되는지** 확인한다
- 조건부 로직(`if element exists`) 안에 핵심 assertion을 넣지 않는다
- `runpy` 테스트에서 mock이 유효한지: 패치 대상이 SOURCE 레벨인지 확인 (`BaseCollector.run` vs `EstimatesCollector.run`)

### 5.6 숫자 전파 오류 (Stale Number Propagation)

한 곳의 숫자를 바꾸고 다른 참조를 업데이트하지 않는 것.

**실제 사례:**
- 에이전트 7개 → 10개 추가 후, README/CLAUDE.md/STRATEGY.md에 "7 agents" 잔존
- 테스트 수 2700 → 2884 업데이트 시 README는 고치고 STRATEGY.md 누락

**방어:**
- 숫자 변경 시 `grep -ri "이전값"` 으로 전수 검색한다
- CLAUDE.md, README.md, STRATEGY.md, 코드 내 주석을 모두 확인한다
- 커밋 메시지에 변경된 숫자를 명시한다 (e.g., "update test counts 2808 → 2884")

### 5.7 하네스 구성 요소 (Harness Components)

LLM 에이전트를 안전하게 운용하기 위한 하네스는 4개 레이어로 구성된다.

| 레이어 | 역할 | 현재 구현 |
|--------|------|----------|
| **Context Files** | 에이전트가 작업 시작 시 읽는 프로젝트 규칙 | `CLAUDE.md` (루트 + frontend), `AGENTS.md`, `docs/STRATEGY.md` |
| **MCP Servers** | 외부 도구 연결 (DB 직접 쿼리 등) | `.mcp.json` → SQLite DB. 필요 최소한만 연결 (토큰 절약) |
| **Skill Files** | 반복 작업 절차 문서화 | 배포: `scripts/deploy.sh`, 검증: `scripts/verify.py`, 마이그레이션: `scripts/migrate_db.py` |
| **Mechanical Enforcement** | 규칙 위반을 문서가 아닌 시스템이 차단 | 아래 상세 |

**Mechanical Enforcement 상세:**

```
린터         ruff check (E/F/W/I) — dead import, unused var 자동 감지
CI 게이트     main-ci-cd.yml — lint + test + coverage threshold + Trivy security
PR 검증      pr-checks.yml — merge conflict, conventional commit, 5MB 파일 제한
로컬 검증     make verify-quick (10초) / make verify-all (커밋 전 필수)
파이프라인     SIEGE gate_check.py — exit 1 if BLOCKED (데이터 품질 미달 시 파이프라인 차단)
```

**엔트로피 자동 관리 (Code Garbage Collection):**

코드베이스는 시간이 지나면 엔트로피가 증가한다. 이를 자동으로 관리하기 위한 메커니즘:

| 엔트로피 유형 | 감지 | 방어 |
|--------------|------|------|
| Dead code | `ruff` (F401 unused import, F841 unused var) | CI에서 자동 차단 |
| Stale data | Freshness SLA (`nuri/core/freshness.py`) | WARN/FAIL → 대시보드 경고 |
| Stale tests | Coverage regression 감지 (Codecov PR comment) | 커버리지 하락 시 PR 경고 |
| Schema drift | `schema_version` 테이블 + `_MIGRATIONS` 리스트 | `init_db()` 시 자동 마이그레이션 |
| Config drift | `config/*.yaml` 중앙 관리 | 코드에 하드코딩 금지 원칙 |
| Number drift | 숫자 변경 시 `grep -ri` 전수 검색 | 커밋 메시지에 변경 숫자 명시 |

**Context Files 설계 원칙:**

- 거대한 하나의 파일 ✕ → 디렉토리별 맵 ✓ (`CLAUDE.md`는 루트 + frontend 분리)
- 코드에서 유추 가능한 정보 ✕ → 코드만으로 알 수 없는 결정의 "왜"만 기록
- `STRATEGY.md`는 반드시 작업 시작 전에 읽도록 `CLAUDE.md`에 지시

### 5.8 하네스 원칙 요약

```
1. 모르면 읽는다         — 가정하지 않는다
2. 2번 실패하면 접근을 바꾼다  — 같은 시도 3회 금지
3. 수정 후 실행한다       — 논리적 확신을 신뢰하지 않는다
4. 스코프를 지킨다       — 요청된 것만 한다
5. 숫자를 grep한다       — 한 곳만 고치지 않는다
6. 시스템이 차단한다      — 문서가 아닌 린터/CI/게이트가 강제한다
```

---

## 6. SIEGE 10-Gate 명세

모든 추천은 이 10개 조건을 통과해야 CERTIFIED 된다. 1개라도 error 등급 실패 시 REJECTED.

| # | 조건 | 등급 | 기준 |
|---|------|------|------|
| 1 | position_limit | error | 단일 종목 ≤ 15% |
| 2 | sector_limit | error | 섹터 ≤ 35% |
| 3 | stop_loss_growth | error | 성장주 손절 -7% 준수 |
| 4 | stop_loss_value | error | 가치주 손절 -10% 준수 |
| 5 | data_fresh | warning | SPY 데이터 ≤ 72시간 |
| 6 | leverage_ban | error | 금지 ETF (TSLL, TQQQ 등) 미보유 |
| 7 | vix_gate | warning | VIX > 30일 때 신규 매수 없음 |
| 8 | external_data | warning | 외부 데이터 ≥ 10건 존재 |
| 9 | conflict_free | warning | 동일 종목 BUY/SELL 충돌 없음 |
| 10 | drift_safe | warning | 매수 후보에 critical drift 시그널 없음 |

---

## 7. 앞으로 진행할 순서

이 섹션은 **앞으로 할 일**만 기록한다. 완료된 항목은 git log + closed PR + closed issue가 진실 source. 새 작업을 시작하기 전에 이 순서를 확인하고, 새 발견은 GitHub 이슈로 등록한 뒤 이 표에 추가한다.

### Tier 1 — 다음 1~2 작업 사이클 (P0)

가장 시급. 파이프라인 안정성·신뢰도·시스템 가치 명제 직결.

| # | 항목 | 이슈 | 카테고리 | 비고 |
|---|------|------|---------|------|
| 1 | **macro intelligence ingestion** (뉴스·이벤트 → regime classifier) | [#137](https://github.com/researcherhojin/nuri-quant/issues/137) | feat(macro) | **시스템의 raison d'être 직결.** 휴전·유가·sector rotation 같은 이벤트를 시스템이 모르면 사용자가 시스템보다 더 많이 알게 되어 본말 전도. macro_score 56/100 lock 해제. |
| 2 | consensus 15초 timeout 크래시 수정 | [#130](https://github.com/researcherhojin/nuri-quant/issues/130) | fix(agents) | `make full-scan` Phase E 중단 사유. 60초로 상향 + per-future timeout 패턴 |
| 3 | SIEGE REJECTED → 행동 가능 remediation | [#132](https://github.com/researcherhojin/nuri-quant/issues/132) | feat(siege) | certify + rebalance를 한 번에. `make remediate` 신규 |
| 4 | 상장폐지 한국 ETF 6개 정리 + 자동 검증 | [#131](https://github.com/researcherhojin/nuri-quant/issues/131) | chore(data) | 로그 오염 + Phase F warn. portfolio 검증 스크립트 추가 |
| 5 | 개인 금융 데이터 git/PR/issue 노출 금지 룰 명문화 | [#138](https://github.com/researcherhojin/nuri-quant/issues/138) | chore(privacy) | pre-commit hook + CI scan + STRATEGY.md §4.4 강화 (이미 일부 반영) |

### Tier 2 — 다음 1 달 (P1)

전략적 가치 큼. Tier 1 끝나고 진행.

| # | 항목 | 이슈 | 카테고리 | 비고 |
|---|------|------|---------|------|
| 4 | 티커 기반 First-Run 온보딩 UX | [#133](https://github.com/researcherhojin/nuri-quant/issues/133) | feat(frontend) | 신규 사용자 0분 가치 체험. `/analyze?ticker=NVDA` |
| 5 | 포트폴리오 온보딩 UI (YAML → Dashboard) | [#25](https://github.com/researcherhojin/nuri-quant/issues/25) | feat(frontend) | 수동 yaml 편집 제거 |
| 6 | 백테스트 인터랙티브 equity curve | [#89](https://github.com/researcherhojin/nuri-quant/issues/89) | feat(frontend) | 파라미터 sliders + 실시간 시뮬레이션 |
| 7 | rebalance-advisor priority 필드 노출 | [#87](https://github.com/researcherhojin/nuri-quant/issues/87) | feat(api) | 매도 우선순위 명시 |
| 8 | 서비스 아키텍처 Mermaid + README 뱃지 미니멀화 + DX_GUIDE 한글화 | [#134](https://github.com/researcherhojin/nuri-quant/issues/134) | docs | Palantir-style 토폴로지 시각화 |
| 9 | SECURITY.md + Community Health 100% | [#135](https://github.com/researcherhojin/nuri-quant/issues/135) | chore(security) | 보안 보고 채널 + diskcache dismissal 영구 문서화 |

### Tier 3 — 다음 분기 (P2)

큰 작업. 선행 종속성 또는 외부 통합.

| # | 항목 | 이슈 | 카테고리 | 비고 |
|---|------|------|---------|------|
| 10 | Alpaca 실전 연동 (Paper → Live) | [#17](https://github.com/researcherhojin/nuri-quant/issues/17) | feat(execution) | 자동 매도 실행. SIEGE CERTIFIED 종목만 |
| 11 | KIS Open API 한국 실전 연동 | — | feat(execution) | `kis_realtime.py` 기 구현. 매매 endpoint 미연결 |
| 12 | pytest fast/slow marker 분리 | [#88](https://github.com/researcherhojin/nuri-quant/issues/88) | ci | PR feedback 가속 (현재 CI 약 2:47, slow split 시 ~1:30 목표) |

### 영구 배경 작업 (낮은 우선순위, 발견 시 처리)

| 항목 | 이슈 | 비고 |
|------|------|------|
| Position special regime trend matching | [#86](https://github.com/researcherhojin/nuri-quant/issues/86) | substring → state.trend 정확 매칭 |
| TestGate flake on push (PR-only pass) | [#85](https://github.com/researcherhojin/nuri-quant/issues/85) | CI 환경 차이 조사 필요 |

### 작업 규칙 (변경 없음)

- **이슈 1개 = PR 1개**, 커밋 ≤ 3
- 새 발견 → 별도 이슈, 같은 PR에 묶지 않음
- Tier를 건너뛰지 않음 (Tier 2 시작 전 Tier 1 모두 close)
- 새 항목 추가 시 이 표를 함께 업데이트, 이슈 번호 필수

---

## 8. 오픈소스 레퍼런스

이 프로젝트의 설계에 영향을 준 출처. 새로운 기능을 설계할 때 이 레퍼런스를 먼저 확인한다.

### 투자 이론

| 출처 | 적용 | 코드 위치 |
|------|------|----------|
| O'Neil, *CAN SLIM* | 손절 -7%, 익절 +20%/+40%, 8주 보유 규칙 | `config/rules.yaml` |
| Minervini, *SEPA* | 트레일링 -15%, 3:1 손익비 | `config/rules.yaml` |
| Shefrin & Statman, 1985 | 처분효과 경고 (조기 익절 편향) | 익절 규칙의 이론적 근거 |

### 아키텍처/엔진

| 출처 | 적용 | 코드 위치 |
|------|------|----------|
| [SIEGE Engine](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution) | 10-gate, certification, event journal | `nuri/trading/engine/` |
| [Palantir Foundry](https://www.palantir.com/docs/foundry/data-lineage/overview) | Data Health, pipeline 모니터링 | `nuri/core/freshness.py`, `events.py` |
| [Dagster](https://docs.dagster.io/guides/observe/asset-freshness-policies) | Freshness SLA (PASS/WARN/FAIL) | `nuri/core/freshness.py` |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | 멀티에이전트 합의 패턴 | `nuri/trading/agents/` |
| [Riskfolio-Lib](https://riskfolio-lib.readthedocs.io/) | Risk Parity 최적화 | `nuri/analysis/rebalance.py` |
| [VectorBT](https://vectorbt.dev/) | 벡터 기반 백테스트 | `nuri/quant/backtest/engine.py` |

### UX

| 출처 | 참고 |
|------|------|
| [Ghostfolio](https://github.com/ghostfolio/ghostfolio) | 미니멀 대시보드, progressive disclosure |
| [React Flow](https://reactflow.dev/) | 파이프라인 DAG 시각화 |
| [FreqUI](https://www.freqtrade.io/en/stable/freq-ui/) | 백테스트 시그널 마커 |
