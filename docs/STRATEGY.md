# Nuri-Quant 전략 정의서

이 문서는 프로젝트의 존재 이유, 핵심 설계 결정의 근거, 개발 품질 기준을 정의한다. 새로운 기능을 만들거나 기존 구조를 변경할 때 이 문서의 원칙에 부합하는지 먼저 확인한다.

---

## 1. 왜 이 프로젝트를 만들었는가

**문제**: 개인 투자에서 감정과 직감에 의존하면 처분효과(Shefrin 1985)에 빠진다 — 수익 종목은 너무 빨리 팔고, 손실 종목은 너무 오래 잡는다.

**가설**: "왜 사야 하는지/팔아야 하는지"를 데이터로 증명하는 시스템을 만들면, 감정 개입을 제거하고 일관된 의사결정을 할 수 있다.

**핵심 차별점**: 추천을 내리는 것이 아니라, 추천의 근거를 증명하는 것이 목적이다.
- 20개 시그널 × 8,000+ 과거 트레이드 백테스트로 각 시그널의 승률/수익비(PF)를 검증
- 10개 에이전트가 독립적으로 분석한 뒤 가중 합의 (risk agent 거부권)
- SIEGE 11-gate가 모든 추천을 기계적으로 검증 — 1개라도 실패하면 REJECTED
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
- **execution_priority** (PR #200): 손절 → 익절 → 트레일링 설정 → 신규매수 순서 고정. 출혈 차단이 수익 확정보다 선행한다. 손절 내에서는 손실률 큰 것부터, 익절 내에서는 타겟 초과율 큰 것부터.
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
- SIEGE certification: 11개 조건의 pass/fail 결과가 매번 기록됨.
- **새 기능을 만들 때**: "이 기능이 실패하면 어떻게 알 수 있는가?"를 먼저 답하라.

### 2.5 비용 최소화 + 데이터 sovereignty (Lean-cost stack)

유료 API, 클라우드 서비스, 상용 소프트웨어 의존도를 최소화한다. 100% 무료를
교조적으로 고수하지는 않는다 — 의미 있는 quality 향상이 명확히 정량화되고
연간 비용이 이자 한 잔 수준이며, 데이터 sovereignty 룰(아래 §4.4.3)을
지킬 수 있을 때는 도입을 허용한다.

| 선택 | 이유 |
|------|------|
| SQLite (not Postgres) | 별도 서버 불필요. WAL 모드로 동시 읽기. `tmp_path`로 테스트 격리. |
| **Hybrid LLM stack** | 정책 (2026-04-14 개정): (a) 공개 RSS 헤드라인 분류 → **OpenAI gpt-5.4-nano** (Tier 0, ~\$3.51/yr). (b) 일간 LLM 리포트 → **OpenAI gpt-5.4-nano** (Tier 2, ZDR 필수, 프로토타입 단계 임시 허용). (c) 사용자 narrative / Tier 1 → 현재 미허용. **로컬 LLM 전환 계획**: 사용자가 Ollama/llama.cpp 인프라 확정 시 (b)를 local로 이관. 비활성화: `NURI_DISABLE_EXTERNAL_LLM=1`. 상세: §4.4.3. |
| OpenBB + yfinance (not Bloomberg) | 무료 데이터. OpenBB 추상화 → provider 교체 용이. yfinance는 폴백. |
| GitHub Actions (not Jenkins) | 오픈소스 무료 tier. lint + test + coverage + security 자동화. |

### 2.6 Escalation Ladder (근거 기반 → 기계적 차단의 3단계)

§2.1 (Evidence-first)와 §2.2 (Mechanical execution)는 같은 스펙트럼의 양 끝이다. 모든 반대 증거에 대해 어디까지 기계적 개입을 할지는 3단계 사다리로 결정한다. 새 feature 설계 시 이 단계를 **명시적으로** 고르고 PR/STRATEGY 에 기록한다.

| 단계 | 행동 | 언제 | 구현 예시 |
|------|------|------|----------|
| **Surface** | 증거 노출만 (UI 배지, reasoning, log). action/confidence 불변. | 신호가 plausible 하지만 noisy, sparse, outcome-검증 부족. 사용자 판단 여지 유지. | PR #301 `divergence_flag` 감지, PR #302 UI 배지 |
| **Soft penalty** | 결정적 downgrade/reweight (action HOLD 전환, confidence cap). 차단은 아님. | 같은 반대 시그널이 반복 감지되고, downside skew 는 명확하지만 universal fatal 은 아닐 때. config 로 tunable. | PR #303 `divergence_technical_threshold` (default 80), `config/agents.yaml` |
| **Hard veto** | 해당 조건이 성립하면 action 강제 변경 또는 차단 (BUY 억제 포함). config 건드리기 어렵게. | 역사적으로 수용 불가, 정책 수준, 위험의 risk-of-ruin 성격. 투자 규칙 급. | Risk agent 거부권 (consensus.py:181, SELL + conf ≥ 80), execution_priority (PR #200), VIX > 30 신규 매수 차단 |

**운용 원칙**:
1. Surface → Soft penalty 이관은 **데이터 기반** 결정. penalty 를 정당화할 "발동 빈도 + 적중률" 측정이 선행. `pipeline_events` 에서 `consensus_penalty_applied` 같은 감사 이벤트로 수집.
2. Soft penalty → Hard veto 이관은 **정책/이론 기반** 결정. STRATEGY 개정 PR + 백테스트 증거 필수.
3. 등급 상향은 쉽고, 하향은 어렵다 (한 번 mechanical 로 올린 것을 informational 로 내리면 과거에 차단된 case 의 해석이 모호해짐).

**Anti-pattern**: §2.1 "Evidence-first" 를 이유로 모든 것을 Surface 에 두면 P1 A1/A2 의 JKHY 에피소드처럼 ⚠ 배지가 실제 행동을 바꾸지 않는 "performative 경고" 가 된다. 반대로 모든 반대를 Hard veto 로 올리면 trade 기회 손실 + 사용자의 판단권 박탈. 3단계 구분이 명시적 framework.

**변경 절차**: 단계 이동은 config 또는 docs 만 건드리는 PR 로. 코드에 매직 넘버 추가하는 방식으로 step 승격 금지 (§2.2 "규칙을 바꾸고 싶으면 YAML을 수정" 원칙).

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
| **execution_priority** (손절>익절>트레일링>신규매수) | 하락 모멘텀의 1시간 지연 = 추가 손실 확정. 상승 모멘텀은 상대적으로 견딤. | 자체 재무 논리 (PR #200) |
| **trailing_stop_arm +15%** | 수익이 자연스럽게 되돌아가는 give-back 방지 | active 전략 신규 (PR #202) |
| **decisions 결과 추적** | 경험 기반 신뢰도: 에이전트별 적중률을 모아 가중치 동적 조정 | Decision Intelligence (PR #181, #183) |

### 3.5 계좌별 전략 프로파일

`config/rules.yaml`의 `account_strategies` 섹션에 정의. `portfolio.yaml`의 각 계좌 `strategy` 필드와 매칭.

| 전략 | 손절 | 단일종목 | 섹터 | 특이사항 | 의도 |
|------|------|--------|------|---------|------|
| **core** | -7% | 15% | 35% | — | 정석 운용. Main 계좌 기본값 |
| **active** | -10% | 25% | 45% | `trailing_stop_arm: 15` | 적극 운용 — 손실은 짧게, 수익은 보호하며 길게 (PR #202) |
| **swing** | -15% | 30% | 50% | — | 단기 회전 (5~20일 보유) |
| **long_term** | -20% | 25% | 50% | — | 장기 보유, 변동성 감수 |
| **pension** | -30% | 40% | 60% | — | 연금 ETF, 초장기 리밸런싱 |

**선택 가이드:**
- **Core**: 빠른 손절로 보수적 운용, 위너 규모 작음
- **Active**: -10% 이내 컷 + 위너 25%까지 + +15% 트레일링 자동 발동 → "손실은 짧게, 수익은 길게" 최적화
- **Swing**: -15% 허용은 누적 손실 위험. 진짜 단기(5~20일)에만 적용
- **Long_term / Pension**: 장기 ETF 위주, 단기 변동 무시

규칙 변경 절차: `config/rules.yaml` 수정 → 백테스트 검증 → PR. 코드에 예외 분기 금지.

---

## 4. 개발 품질 기준

PR을 올리기 전 이 기준을 확인한다.

### 4.1 테스트

| 항목 | 기준 | 현재 |
|------|------|------|
| Backend tests | 고정 minimum 없음 — Codecov 1% relative regression gate (목표 ≥ 95%) | 2,951 tests, 137 files |
| Frontend tests | 목표 ≥ 90% | 913 tests, 60 files |
| E2E | 핵심 flow 커버 | 38 Playwright tests (6 spec) |
| CI 통과 | 필수 | lint + test + coverage + security + privacy |
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
| LLM | **사용자 portfolio·narrative·의사결정 데이터는 외부 LLM 전송 금지 (Ollama local only).** 공개 RSS 헤드라인 분류는 §4.4.3의 외부 LLM Egress Policy에 등재된 provider 한정으로 허용. 새 데이터 클래스 추가는 STRATEGY 개정 + 본인 명시 승인 필수. |
| **개인 금융 데이터** | commit · PR · issue · 코드 주석 · 테스트 fixture · CI 로그에 절대 노출 금지. `config/portfolio.yaml`이 gitignored이지만 그 *내용*도 git 추적 대상에 들어가면 안 됨. broker 계좌명, 보유 수량, 평단가, 현금 잔고, 매매 이력 모두 해당. 자세한 룰은 아래. |

#### 4.4.1 개인 금융 데이터 enforcement (#138)

**권위 있는 차단 기준** — 문서가 아닌 시스템이 강제. `scripts/check_privacy_leak.py`에 정의된 패턴이 ground truth.

| 카테고리 | 차단 대상 | 허용 placeholder |
|---|---|---|
| Korean broker name | Brokerage Alpha, Brokerage Beta, 키움증권, 삼성증권, NH투자증권, 토스증권, KB증권, 신한투자증권, 하나증권, 메리츠증권, 유안타증권, 대신증권, 이베스트투자증권, 흥국증권, IBK투자증권 | `Brokerage Alpha`, `Brokerage Beta`, `Brokerage Alpha Cash Account`, `Brokerage Alpha Securities` |
| Romanized broker | kakaopay, mirae, kiwoom, samsung_securities, nh_invest, toss_securities, shinhan_invest, hana_securities, meritz_securities (case-insensitive substring) | 동일 — 한글 placeholder를 영문 식별자로 변환 시 `brokerage_alpha` 등 사용 |
| Suspect monetary literal | 7자리 이상 정수 (`>= 1_000_000`) 가 동일 라인에 `total_invested`, `cash_balance`, `deposit`, `withdraw`, `principal`, `net_worth`, `buying_power` 키와 함께 존재 | round million 값 (`1_000_000`, `5_000_000`, …, `100_000_000`)은 placeholder로 자동 허용 |
| **Ticker + PnL 조합** (PR #202 class) | 두 패턴 중 하나 — (a) `[-+]\d+(\.\d+)?%\s*(TICKER)` 형태 (`-34% (TEM)`) (b) 인접한 `TICKER <signed %>` (`PL +43%`). 소스 파일 **+ unpushed commit messages** 모두 스캔. | 규칙 threshold 텍스트 (`손절 -7%`, `트레일링 -15%`)는 ticker 컨텍스트 없으면 통과. `TICKER_FALSE_POSITIVES` frozenset (HWM/SL/MDD/CPI/VIX/BTC/ETH 등 120개 abbreviation)은 ticker로 간주하지 않음. |

**의도적 제외**:
- `한국투자증권` (KIS) 은 Open API 통합 대상으로 코드베이스에 합법적으로 등장 (`nuri/collectors/kis_*`, `docs/KIS_INTEGRATION.md`). 사용자 개인 KIS 자격 증명 위치는 `config/kis/kis_devlp.yaml` (프로젝트 내 gitignored by `config/kis/*` 패턴, `~/KIS/` 레거시 위치도 하위 호환으로 자동 감지). broker name 패턴이 아닌 **credential file 패턴** + **디렉토리 whitelist 패턴** 두 층으로 차단.

**방어 layer 3개** (defense in depth):
1. `scripts/check_privacy_leak.py` — 핵심 scanner. stdlib only, no deps.
2. `scripts/pre_push_check.sh` Section 4 — local pre-push gate. 로컬에서 실수 자동 차단.
3. `.github/workflows/main-ci-cd.yml` `privacy-scan` job — CI gate, 모든 PR에서 항상 실행 (frontend-only PR도 예외 없음). 머지 차단.

**새 broker name 추가 시**: `scripts/check_privacy_leak.py`의 `BROKER_NAMES_KO` / `BROKER_NAMES_EN` 튜플에 추가. 테스트는 `tests/test_check_privacy_leak.py`. 이 표도 같이 갱신.

**Commit message 스캔 작동 방식 (PR #202 방지)**:
- `scripts/pre_push_check.sh` Section 4b: `origin/main..HEAD` 범위의 모든 unpushed commit message를 `--unpushed-commits` 모드로 스캔 → push 차단
- 로컬 hook이 정답 — push 후에는 git history에 박혀 제거 불가 (Stage 2 절차 필요)
- CLI: `git log -1 --format=%B | python scripts/check_privacy_leak.py --message`

**History cleanup (Stage 2 — 별도 작업)**:
이 enforcement는 main HEAD를 깨끗하게 유지. 그러나 leak이 처음 들어간 이전 commit(들)은 force push 또는 GitHub Support 요청 없이는 제거 불가. STRATEGY.md §5.4 (스코프 팽창) + CLAUDE.md (force push to main 금지)를 동시에 준수하기 위해 별도 작업으로 분리. 권장 순서: GitHub Support 요청 (비파괴) → 만족 못 하면 `git filter-repo` (사용자 명시 force-push 승인 필수).

**알려진 미정리 leak (Stage 2 후보)**:

| commit | 내용 | 상태 |
|--------|------|------|
| PR #202 (squash 머지) | commit message body에 사용자 보유 종목 + 손실률 (TEM/RKLB/TSLA/PL + PnL) | main git history에 박힘. Stage 2 미실행 |

§4.4.1 enforcement는 PR #202 이후 **ticker + PnL** 사각지대가 보완됨. 같은 방식의 신규 leak은 commit message 단계에서 차단. 다만 PR #202 commit 본문은 git history에 남아 있어 §4.4.1 "알려진 미정리 leak"으로 유지 — history cleanup은 Tier 3 별도 작업 (Stage 2).

#### 4.4.2 외부 데이터 처리 원칙

§4.4 LLM 룰의 일반화. 모든 외부 서비스(LLM, API, webhook 등)는 **데이터 클래스별 화이트리스트** 방식으로 운영한다.

| 데이터 클래스 | 기본 정책 | 외부 전송 허용 조건 |
|---|---|---|
| **Tier 0 — 공개 데이터** (RSS 헤드라인, 공시, 시세, ETF holdings 13F) | 외부 송신 가능 | §4.4.3 등재 provider 한정 |
| **Tier 1 — 사용자 narrative** (주간 view, 정성 판단, 메모) | 외부 송신 금지 | 향후 STRATEGY 개정 + 본인 명시 승인 + retention 정책 결정 후에만 |
| **Tier 2 — 사용자 portfolio** (broker, 보유종목, 평단가, 비중, 현금, 매매 이력) | **절대 외부 송신 금지** | (3) 전체 reasoning 도입 시 별도 STRATEGY 개정 + ZDR 검토 + 본인 명시 승인. 현 시점 미허용. |

§4.4.1 broker name / monetary literal 차단은 Tier 2 데이터의 leak 방지가 직접적 목적. §4.4.3 외부 LLM Egress Policy는 Tier 0 데이터의 명시적 화이트리스트.

#### 4.4.3 외부 LLM Egress Policy (#152, 2026-04-14 개정)

외부 LLM 사용은 **화이트리스트** 방식. 모든 호출은 `nuri/llm/openai_client.py` 단일 관문을 거친다.

**등재 provider + 데이터 클래스**

| Provider | Model | 허용 데이터 클래스 | 단가 (in/out per 1M) | ZDR | 비고 |
|---|---|---|---|---|---|
| OpenAI | `gpt-5.4-nano` | **Tier 0** (공개 RSS 헤드라인 분류) | $0.20 / $1.25 | 권장 | 일 100 헤드라인 기준 연 ~$3.51 |
| OpenAI | `gpt-5.4-nano` | **Tier 2** (LLM 일간 리포트 — 보유 종목/손익/전략) | $0.20 / $1.25 | **필수** | 일 1회, ~3K in + 2K out = 연 ~$0.10. 2026-04-14 사용자 명시 승인 (프로토타입 단계; 향후 local LLM 전환 계획) |

**Tier 2 허용의 전제조건 (2026-04-14 추가)**

사용자가 Option C(본인 명시 승인)를 선택하면서 Tier 2 → `gpt-5.4-nano` 송신이 허용됨. 전제:

1. **ZDR(Zero Data Retention) 필수** — OpenAI에 ZDR 승인 요청이 완료되어야 첫 Tier 2 호출 가능. 미승인 상태에서 Tier 2 호출 시 wrapper가 환경변수 `OPENAI_ZDR_APPROVED=1` 미설정으로 인해 raise.
2. **`NURI_DISABLE_EXTERNAL_LLM=1`로 즉시 opt-out 가능** — 오프라인/CI/심사 모드에서 일괄 차단.
3. **프롬프트 로그 금지** — wrapper는 토큰 수·지연·에러 타입만 기록, **content는 절대 DB에 남기지 않는다**.
4. **로컬 LLM 전환 계획** — 프로토타입 단계 임시 허용. 사용자가 Ollama/llama.cpp로 전환하는 시점에 Tier 2 제거 PR 예정.

**필수 운영 룰 (전 Tier 공통)**

1. 모든 외부 LLM 호출은 wrapper(`openai_client.get_client()`)를 거친다. 직접 `import openai` 금지.
2. **Per-call audit log** — `external_llm_calls` 테이블에 `timestamp, provider, model, endpoint, prompt_tokens, completion_tokens, latency_ms, success, error_type` 기록. **content는 금지**.
3. **Opt-out** — `NURI_DISABLE_EXTERNAL_LLM=1` 시 wrapper는 `ExternalLLMDisabled` raise.
4. **Failure loud** — OpenAI 실패 시 wrapper는 명시적으로 raise (silent fallback 금지). caller가 graceful degradation 책임 (예: `nuri/llm/report.py`는 OpenAI 실패 시 "[LLM 연결 실패]" 문자열 반환 + Ollama가 설정되어 있으면 secondary로 시도).
5. **Provider 추가** — 신규 provider 등재는 STRATEGY 개정 PR 필요.
6. **데이터 클래스 확장** — Tier 1 (narrative) 또는 추가 Tier 2 경로 확장은 별도 STRATEGY 개정 + 본인 명시 승인.

**의도적 비결정 사항 (deferred until needed)**

- **Narrative input UI** — Tier 1 정책 결정 이후에 설계.
- **외부 LLM 비용 모니터링 대시보드** — `external_llm_calls` 테이블 기반. 월/모델별 비용 + token 추이. 일일 사용량이 예상치 초과 시 알림. 필요 시점에 추가.
- **Tier 2 → local LLM 전환 시점** — 사용자가 Ollama/llama.cpp 운영 인프라 확정 후.

**모니터링 시작 트리거**

이 정책은 #152가 닫히는 시점(Step 2 머지)부터 발효. 2026-04-14 Tier 2 추가 이후 1주일 동안 `external_llm_calls` 테이블의 LLM 리포트 호출 비용이 예상치 (~$0.02/주) 대비 10배 초과 시 사용자 알림 + 즉시 `NURI_DISABLE_EXTERNAL_LLM=1` 복귀 권장.

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
- **`df.copy()` 누락 재발** (2026-04-15, PR #306 CI Shard 2 fail → #307): PR #294/#295 가 "`_standardize(df)` 진입 시 `df = df.copy()`" 를 "의도한 방어" 라 commit message 에 기록하고 CLAUDE.md gotcha 에도 추가했지만 **실제 `nuri/collectors/stock.py` 에는 `df.copy()` 가 없었음**. `mock.return_value = df_fixture` 가 ThreadPoolExecutor 10-worker 에 공유 → `df.columns = ...` race → `pandas.errors.InvalidIndexError`. 수 세션 후 재발. Fix + `TestStandardizeThreadSafety` regression test 를 함께 ship 해 re-collapse 불가능하게 lock-in.

**방어:**
- 수정 후 반드시 테스트를 실행한다. "논리적으로 맞을 것"을 신뢰하지 않는다
- 테스트가 통과하더라도 **의도한 라인이 실제로 커버되는지** coverage 리포트로 확인한다
- `vi.mock()` 사용 시 hoisting 영향 범위를 인식한다 (파일 단위, 워커 단위)

#### 5.3.1 Gotcha-Test Pair 원칙 (PR #307)

`df.copy()` 재발 교훈. Gotcha 가 **folklore** (이야기) 로만 기록되면 다음 리뷰어가 해당 defensive 코드를 "불필요해 보임" 이라 제거해도 테스트가 안 막는다. **모든 fix-pattern gotcha 는 그 fix 가 사라졌을 때 fail 하는 test 를 명명해서 cite 해야 한다**.

**프로토콜**:
1. Gotcha 문장 끝에 `**Test:** `path/to/test.py::TestClass::test_name`` 추가.
2. Cited test 는 **fix 가 없을 때 실제로 fail** 해야 함 (테스트 자체가 phantom 이면 안 됨). PR 에서 fix 를 임시로 revert 해 test 가 fail 하는지 local 검증 권장.
3. Gotcha 가 단순 facts/quirks (e.g. "yfinance .KS fundamentals work") 이고 fix 절차가 아닌 경우 Test: 불필요.
4. 새 gotcha 추가 시 Test: 없이 ship 하려면 PR body 에 "no fix, just facts" 명시.

**Enforcement**:
- 1차 (지금): 리뷰 checklist + STRATEGY §5.3.1 참조. 사람 규율.
- 2차 (Tier 3 후보): `scripts/audit_phantom_fixes.py` — CLAUDE.md Gotchas 파싱 → 각 `**Test:**` 참조가 실존 테스트인지 verify → CI lint. 인간 규율 drift 방지.

**관련**: STRATEGY §5.5 (Test Illusion), §5.8 원칙 1 "모르면 읽는다" — gotcha 는 "고쳤다" 는 이야기, 실제 고침은 코드에서 확인.

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

- 거대한 하나의 파일 ✕ → 디렉토리별 맵 ✓ (`CLAUDE.md` 루트 + 7개 디렉토리 scoped `CLAUDE.md`)
- 코드에서 유추 가능한 정보 ✕ → 코드만으로 알 수 없는 결정의 "왜"만 기록
- `STRATEGY.md`는 반드시 작업 시작 전에 읽도록 `CLAUDE.md`에 지시

### 5.8 하네스 원칙 요약 (2026-04-14 #272 세션 반영, 7개)

```
1. 모르면 읽는다              — 가정하지 않는다
2. 2번 실패하면 접근을 바꾼다  — 같은 시도 3회 금지. 같은 fix가 3번에 걸쳐
                                부분만 해결하면 root cause 의심
3. 사용자 워크플로로 검증한다  — mock test ≠ verification.
                                ship 전 `make X --flag` 직접 실행
4. 스코프를 지킨다            — 요청된 것만 한다
5. 숫자를 grep한다            — 한 곳만 고치지 않는다
6. 시스템이 차단한다          — 문서가 아닌 린터/CI/게이트가 강제한다
7. 외부 API는 측정한다        — 동시성/timeout/rate-limit 추정 금지.
                                yfinance 10-thread OK ≠ KRX 10-thread OK
```

**변경 이력**:
- 2026-04-14: #3 강화 ("실행한다" → "사용자 워크플로로 검증한다"), #7 추가 (외부 API 측정). Mock-only ship 함정 3회 반복 후 추가 (#5.9 참고).

### 5.9 #272 세션 교훈 (2026-04-14, 12 PRs)

**Universe + Agent Coverage 통합**(#272) 작업에서 8시간에 걸쳐 12개 PR 머지하며 누적된 패턴 — 미래 비슷한 작업에서 반복 실수 회피용.

#### 5.9.1 Mock-only 테스트 함정

| 사례 | 상황 | 결과 |
|------|------|------|
| PR #278 universe mode | mock test 28건 통과 → ship → 사용자 실행 시 yfinance ERROR 500줄 | rebuild 필요 |
| PR #282 ThreadPool timeout | unit test 통과 → ship → 사용자 실행 시 여전히 hang | 2차 fix |
| PR #283 sequential fix | live 검증 33초 → 머지 → 끝 | 처음으로 정상 ship |

**룰**: ship 전 사용자 워크플로 1회 직접 실행. mock test와 별개로 `make X --source universe` 같은 실제 명령. `tests/integration/` marker (`@pytest.mark.integration`)로 분리하되 ship 게이트에 포함.

#### 5.9.2 외부 API 동시성 차이

| API | 동시 요청 | 패턴 |
|-----|----------|------|
| yfinance | **10 thread OK** | `ThreadPoolExecutor(max_workers=10)` |
| KRX (pykrx) | **rate-limit, sequential 권장** | 순차 + `time.sleep(0.1)` |
| Wikipedia | 10초 간격 권장 | User-Agent 헤더 + backoff |

**룰**: 새 외부 API 통합 시 동시성 측정 후 결정. ThreadPool은 API 종류에 따라 도움/해악 갈림.

#### 5.9.3 ThreadPool 한계

`ThreadPoolExecutor.future.result(timeout=)`는 future를 cancel만 하고, **underlying C extension call (e.g. pykrx)은 계속 실행** → 누적되어 메모리 leak + slowdown.

**룰**: hang 가능한 외부 호출에 timeout으로 cancel하려 하지 말 것. 진짜 cancellable 필요하면 subprocess 사용. 또는 sleep + 단순 try/except.

#### 5.9.4 Iterative root cause

같은 버그를 3회에 걸쳐 fix:
1. PR #282: ThreadPool timeout 추가 → 부분 해결
2. PR #283: 8 thread parallel → 첫 60건 빠르고 그 후 KRX rate-limit
3. PR #283 (수정): sequential + 0.1s sleep → 진짜 fix

**룰**: 같은 증상 2회 반복 fix 시 근본 원인 의심. 3회 시도 전에 `pytest --pdb` 또는 실제 환경에서 직접 디버깅.

#### 5.9.5 사용자 관점 검증 누락

`make X --flag` 형태로 사용자가 자연스럽게 시도한 명령이 실패 (`make universe-sync --market kr` → make는 arg 안 받음). 사용자가 아는 패턴 ≠ 코드가 지원하는 패턴.

**룰**: Makefile target 추가 시 자주 쓰일 변형(`-us`, `-kr`, `-apply` 등)을 dedicated target으로 명시.

#### 5.9.6 진행 가시성 = 신뢰

543종목 1개씩 처리되는데 progress 표시 없으면 사용자는 "stuck" 판단. tqdm + 명확한 요약은 ship 필수.

**룰**: ≥20 ticker iteration 모든 collector에 tqdm + 요약 (✅ N 성공 / ❌ M 실패) + per-field N/A 진단 추가.

#### 5.9.7 Multi-role flow 강제

PM (spec) → Dev (impl) → Eval (test + smoke) → ship. Eval 단계 건너뛰면 #5.9.1 함정에 빠짐. 본인 self-review가 아닌 별도 단계로 분리할 것.

**룰**: `gstack-codex` 등 외부 review tool 또는 사용자 review 단계 전에 ship 금지. 자동화된 integration test가 review 대체 가능.

### 5.10 추천 파이프라인의 도구 사각지대 (JKHY 에피소드, 2026-04-14)

> **2026-04-15 정정 노트** (PR #307): 원 기록의 핵심 진단 2개가 심층 조사 결과 오독으로 밝혀졌다. 원 문장은 교훈용으로 stryke-through 보존하되 실제 root cause 와 대응은 아래 **"정정된 분석"** 참조.

**상황**: 세션 종료 직전 universe-wide BUY 추천 7종목 (TMUS/JKHY/V/MA/BX/ANET/NFLX) 제시. 사용자가 Investing.com 확인 → JKHY "적극 매도" (기술지표 종합). 시스템 추천과 정면 모순.

~~**원인 (3층)**:~~

1. ~~**도구는 있으나 연결 안 됨** — `nuri/quant/chart_analysis.py` (BB/MACD/RSI/추세선) 구현 존재하지만, 추천 파이프라인 (`candidates.py`, `consensus.py`) 에서 호출하지 않음.~~
2. ~~**Fundamentals-only 추천** — 애널리스트 upgrade + ROE/PE 기반 Buy 신호만 사용. 가격 모멘텀/추세 완전 무시.~~
3. ~~**애널리스트 신호의 lag 속성 간과** — JKHY earnings surprise 4Q 연속 +0.0~0.2% = "soft beat" 성장 stall 신호도 놓침.~~

**정정된 분석** (PR #301-#303 + codex challenge 결과):

1. **TechnicalAgent 는 이미 `analyze_chart()` 호출 중** — `nuri/trading/agents/technical.py:12,78` 에서 import + invoke. 원 진단 "도구 연결 안 됨" 은 소스 코드 읽지 않은 추정이었음 (§5.1 "모르면 읽는다" 위반).
2. **실제 실패 모드 = dissent overwhelmed, not missing** — JKHY 에 대해 TechnicalAgent 가 SELL(100 conf) 정확히 투표함. 하지만 9 개 fundamentals-ish 에이전트가 BUY/HOLD 로 outweighted → 합의 BUY. 문제는 TechnicalAgent 의 dissent 가 사용자에게 **surface 도 안 되고 action 에 영향도 안 주는** 것. 즉 "informational only" design 의 근본 한계.
3. **JKHY 는 soft beat 이 아니다** — 실측 최근 4Q surprise_pct = 0.17 / 0.13 / 0.04 / 0.09 **decimal fraction** (= 4% ~ 17% 정상 beat). 원 기록의 "0.0~0.2%" 는 저장 단위 오독. JKHY 는 오히려 Bartov 2002 / Kasznik 2002 에서 말하는 "meet/beat premium" 수혜 대상. 진짜 실패 모드는 **falling knife** — fundamentals 강 + technicals 무너짐 + 시장이 구조적 우려 (SaaS competitive pressure 등) 를 먼저 price-in.

**재발 방지 룰** (정정된 원인에 맞춰):
- 추천 내기 전 **fundamentals + technicals 충돌 여부** 를 explicit 하게 surface 하고, technical 이 강하게 반대하면 mechanical 로 downgrade (STRATEGY §2.6 Escalation Ladder 참조).
- "System has the tool" ≠ "Pipeline uses its output"; tool 이 있어도 **outcome 에 영향 주는 경로** 까지 integration test 로 검증.
- Academic literature 기록된 증거 (meet/beat premium 같은) 와 **가설이 반대 방향** 이면 literature 우선 — codex challenge 로 cross-check.

**방어 실행 현황** (2026-04-15 완료):
- PR #300 (P1 B): universe 1y OHLCV backfill → TechnicalAgent 가 full chart 분석 가능
- PR #301 (P1 A1): `divergence_flag` backend 감지
- PR #302 (P1 A2): UI 배지 + tooltip surface
- PR #303 (P1 A3): mechanical penalty — tech conf ≥ 80 + 반대 → HOLD downgrade
- PR #306 (Q1): `consensus_penalty_applied` 감사 이벤트 + STRATEGY §2.6 Escalation Ladder + §7 P1 #4 (soft-beat 스펙) Tier 3 이관

**Live 검증**: JKHY 가 이제 `action=HOLD` (was BUY), reasoning "기술지표 반대로 downgrade (tech SELL conf 100 ≥ 80) | ...".

**일반화된 교훈** (정정):
1. "Repo 에 기능이 있다고 해서 production path 에서 outcome 에 영향 주는 건 아님." — 통합 경로 + **mechanical effect** 검증 필수.
2. "초기 진단이 틀리면 후속 모든 처방이 틀린다." — Codex challenge 같은 독립적 adversarial review 를 성급한 fix 전에 넣는 것이 scope + 시간 절약.

---

## 6. SIEGE 11-Gate 명세

모든 추천은 이 11개 조건을 통과해야 CERTIFIED 된다. 1개라도 error 등급 실패 시 REJECTED.

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
| 11 | macro_event_alignment | warning | \|event_score\| ≥ 10 시 경고 |

---

## 7. 앞으로 진행할 순서

이 섹션은 **앞으로 할 일**만 기록한다. 완료된 항목은 git log + closed PR + closed issue가 진실 source. 새 작업을 시작하기 전에 이 순서를 확인하고, 새 발견은 GitHub 이슈로 등록한 뒤 이 표에 추가한다.

### Tier 1 — 완료 (2026-04-13 ~ 04-15)

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
| 6 | **Privacy scanner ticker+PnL pattern** | — | #289 | §4.4.1 ticker+PnL 사각지대 보완. `-34% (TEM)` / `PL +43%` 양 패턴 감지, `origin/main..HEAD` unpushed commit message 스캔 추가, `TICKER_FALSE_POSITIVES` 120개. PR #202 class 차단. |
| 7 | **Shell scripts 전수 shellcheck clean** | — | #290 | 16개 `.sh` (1,504 lines) → shellcheck 0 issues. `set -euo pipefail`, shebang 통일, 실제 버그 fix (trap SC2064, read -r, RSYNC_OPTS array), `make lint-sh` + CI job 추가 |
| 8 | **OpenAI gpt-5.4-nano LLM 리포트 (§4.4.3 Tier 2)** | — | #294 | Ollama 휴면 → OpenAI primary. §4.4.3 정책 개정 (Tier 2 + ZDR 필수). `chat_text()` + `OPENAI_ZDR_APPROVED` 게이트. fallback chain (OpenAI → llama.cpp → Ollama). **부수 fix**: flaky `test_collect_full_flow` `df.copy()` (#295), security-scan 5m→10m timeout, codecov/patch 커버리지 테스트 3개 보강 |
| 9 | **uv sync 충돌 해결 (fastapi <0.129 pin)** | [#277](https://github.com/researcherhojin/nuri-quant/issues/277) | #291 | openbb-core ↔ fastapi version conflict 해결. dependabot ignore 추가 |
| 10 | **KR `n/a (US-only)` 표시 개선** | — | #288 | US_ONLY_TABLES frozenset + `check_universe_coverage.py` + `validate_universe.py` detail. 수집 실패 vs 소스 한계 시각 구분 |
| 11 | **#272 Phase 3 (Eval): validate_universe + US_ONLY 회귀 테스트** | — | #296 | 20 tests: TestUsOnlyTables(4) + TestRunValidation/Print/Main/Fetch(11) + TestOutputFormat(5) |
| 12 | **#272 Phase 4 (UX): Dashboard coverage widget + `/api/coverage`** | — | #297 | `CoverageStatus` widget (5/5 PASS 헤더 + 5-col 테이블 + 소스 한계 footer). 14 tests (backend 5 + frontend 9) |
| 13 | **README drift sync** | — | #309 | collectors 24→26, LLM 우선순위 (OpenAI primary), test counts 2,763→2,934. Codex APPROVED. |
| 14 | **B2 — Learning Memory outcome read 역방향** | — | #310 | `_compute_weights` SELECT 에 `outcome_30d` 누락 + `sqlite3.Row.get()` 없음. 두 층 버그로 수개월간 weight 역방향. Fix + 3 regression (revert-proof). #308 lock-in 해제. |
| 15 | **B1 — recommendations UNIQUE + UPSERT** | — | #311 | `UNIQUE(date, ticker, action)` → `UNIQUE(date, ticker)`. Migration 20 (MAX(id) dedup). `INSERT OR REPLACE` → `ON CONFLICT DO UPDATE` (id 보존 — `trades.recommendation_id` FK 안전). 프로덕션 20 중복 그룹 정리. |
| 16 | **#248 SIEGE v2 Phase 1 — asset-class gates** | [#248](https://github.com/researcherhojin/nuri-quant/issues/248) | #312 | Gate 5/7/8 per-asset-class (us/kr_equity/kr_index/commodity/bond). Cross-market spillover (KOSPI+SPY, USD/KRW+VIX). `config/rules.yaml siege_gates` spec. Codex challenge (3 결함 지적) → 재설계 → APPROVED. |

### Tier 2 — 다음 1 달 (P1)

**다음 세션 우선순위** — 구체적 작업 단위로 엄밀 정의 (2026-04-14 재평가).

| 우선 | # | 항목 | 이슈 | 카테고리 | 예상 | Acceptance |
|------|---|------|------|---------|------|------------|
| 🟡 P1 | 1 | **#272 Phase 5 (QA): Negative + Smoke run** | — | test | 1 세션 (네트워크 필요) | 빈 DB/yaml 삭제 negative 3건 + fresh clone → `make setup` → `make universe-sync-us/kr` → `make collect` → `validate_universe` 실행 기록 → `docs/SMOKE_RUN.md` 작성 |
| 🟡 P1 | 2 | **기술분석 통합 to 추천 파이프라인** | — | feat(recommend) | 1-2 세션 | JKHY 에피소드 (2026-04-14) 재발 방지. `nuri/quant/chart_analysis.py` (BB/MACD/RSI) 을 `candidates.py` / consensus에 자동 연동. "fundamentals Buy, technicals Sell" divergence 플래그 추가 |
| 🟡 P1 | 3 | **가격 히스토리 확장 (5d → 1y+)** | — | ops | 0.5 세션 | `prices` 테이블 5일치만 있음 → 52주 레인지 / 추세선 계산 불가. 정기 `make collect --period 1y` 실행 체계 + scheduler 등록 |
| ~~🟡 P1~~ | ~~4~~ | ~~**Earnings quality 분석 통합**~~ | — | ~~feat(recommend)~~ | ~~0.5 세션~~ | **Tier 3 research 로 이관** (2026-04-15). Codex challenge 로 (a) JKHY 실측 surprise 가 4-17% 정상 beat (STRATEGY §5.10 에 기록된 "0.0~0.2% soft beat" 는 unit 오독에서 온 문서 오류), (b) literature (Bartov 2002, Kasznik & McNichols 2002, Neururer 2020) 는 meet/beat streak 을 **양의** 신호로 본다. 원안 spec 은 repo-wide unit inconsistency + mature large-cap false positive + literature 반대 방향 문제로 **기각**. 재설계는 Tier 3 "#### Tier 3 — research note" 항목 참조. |
| 🟢 P2 | 5 | **포트폴리오 온보딩 UI (YAML → Dashboard)** | [#25](https://github.com/researcherhojin/nuri-quant/issues/25) | feat(frontend) | 2-3 세션 | 수동 yaml 편집 제거. 2026-04-14 portfolio.yaml 수동 수정 페인포인트 직접 경험 |
| 🟢 P2 | 6 | **OpenBB 호환성 fix** | [#274](https://github.com/researcherhojin/nuri-quant/issues/274) | bug(collectors) | 1 세션 | openbb-core==1.6.7 ↔ openbb-news==1.6.1 충돌로 news/etf_flows 수집 불가. 점진적 upgrade 필요 (콜렉터별 smoke test 후 진행) |
| 🟢 P2 | 7 | **백테스트 인터랙티브 equity curve** | [#89](https://github.com/researcherhojin/nuri-quant/issues/89) | feat(frontend) | 1 세션 | 파라미터 sliders + 실시간 시뮬레이션 (PR #269로 일부 완료, 마무리) |
| 🟢 P2 | 8 | **#272 Phase 2c-3 — universe-check 필수 게이트화** | — | ops | 10분 | `make collect-universe` 5/5 PASS 상태 유지 중 → 사용자 수동으로 branch protection required check 토글 |
| 🟢 P2 | 9 | **wallstreet collect 성능 검증** | — | perf(collectors) | 15분 | PR #285 parallel fetch 실제 50min → 15min 41초 (universe 746) 확인 완료 — **close 후보** |
| ⚪ P3 | 10 | **flaky test 일반 stabilization** | — | test | 1 세션 | #295는 resolved. 다른 flaky 후보 (parallel sys.modules 오염 패턴) 전수 감사 |

### Tier 3 — 다음 분기 (P2)

큰 작업. 선행 종속성 또는 외부 통합.

| # | 항목 | 이슈 | 카테고리 | 비고 |
|---|------|------|---------|------|
| 1 | **PR #202 commit message Stage 2 history cleanup** | — | security | 사용자 보유 종목 + 손실률이 PR #202 commit message에 노출되어 main git history에 박힘 (TEM/RKLB/PL 등 + PnL). §4.4.1 Stage 2 절차 (GitHub Support 또는 `git filter-repo`) 적용 결정 필요 |
| 2 | **Universe 추가 확장 (Russell 2000)** | — | feat(scanner) | 현재 419 (us_core 85 + us_sp500 254 + kospi200 80). 중소형주 발굴 위해 Russell 2000 (~2,000) 추가 검토 |
| 3 | **Meet/beat streak research spike** (Tier 2 P1 #4 에서 이관) | — | research | 아래 research note 참조 |

#### Tier 3 — research note: meet/beat streak in revenue-backed growth

**기각된 원안**: `earnings_surprises` 기반 "soft beat" 플래그 (surprise < 2% 지속 3Q → 성장 stall 경고). FundamentalAgent score 에서 -1.

**기각 이유** (2026-04-15 codex challenge + 실데이터 audit):

1. **Unit 오독**: §5.10 에 기록된 "JKHY 4Q 연속 +0.0~0.2%" 는 저장 단위 오해. 실측 JKHY Q4'25~Q1'25 = 0.17 / 0.13 / 0.04 / 0.09 (decimal fraction) → **17% / 13% / 4% / 9% 실 beat** 이 맞음. 4-17% 전부 정상 beat 이고 soft beat 아님.
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

**승격 조건**: 백테스트에서 (b) 가 baseline 대비 +Sharpe/-drawdown 둘 다 유의미 + `pipeline_events` 샘플로 false-positive rate 를 validate 한 후에만 §2.6 Escalation Ladder 의 **Soft penalty** 레벨에 올림.

**참고**: 무작정 소환하지 말 것. 데이터 충분히 축적 (최소 2년 earnings + 4 분기 실시간 backtest) 이후 spike 로.

### 자동 매매 — 영구 deferred (사용자 opt-out)

| 항목 | 이슈 | 결정 사유 |
|------|------|---------|
| Alpaca 실전 연동 (Paper → Live) | [#17](https://github.com/researcherhojin/nuri-quant/issues/17) | **영구 보류**. 2026-04-11 사용자 결정 — 자동 매매로 인한 손실 책임소재 이슈. 시스템 추천(확률적)과 실제 매매(결정적) 사이의 책임 경계가 모호해지는 걸 차단. |
| KIS Open API 한국 실전 매매 endpoint | — | **영구 보류** (동일 사유). `kis_realtime.py`의 **read** endpoint(잔고/가격/drift 모니터링)는 그대로 사용. 매매 endpoint만 연결하지 않음. |

**원칙**: 시스템은 추천과 알림에만 관여한다. 실제 주문은 사용자가 직접 증권사 앱에서 수동 실행한다. `DryRun` mode 및 paper trading 시뮬레이션은 백테스트/검증 용도로 계속 사용 가능.

이 결정을 뒤집으려면 STRATEGY.md 개정 PR + 명시적 재승인 필요.

### 영구 배경 작업 (낮은 우선순위, 발견 시 처리)

| 항목 | 이슈 | 비고 |
|------|------|------|
| TestGate flake on push (PR-only pass) | [#85](https://github.com/researcherhojin/nuri-quant/issues/85) | classify_regime mock leak 수정 완료 (#188). 재발 시 추가 조사 |
| portfolio.yaml 데이터 정합성 모니터링 | — | 수동 매매 후 portfolio.yaml 동기화 필요. 평균가 drift 발견 시 즉시 교정 (사례: PR #204 세션에서 Sub RKLB avg \$60→\$87.7 발견) |

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
| [SIEGE Engine](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution) | 11-gate, certification, event journal | `nuri/trading/engine/` |
| [Palantir Foundry](https://www.palantir.com/docs/foundry/data-lineage/overview) | Data Health, pipeline 모니터링, Decision Intelligence (#178) | `nuri/core/freshness.py`, `nuri/core/events.py`, `decisions` 테이블 (PR #181 shipped) |
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
