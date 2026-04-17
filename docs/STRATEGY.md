# Nuri-Quant 전략 정의서

이 문서는 프로젝트의 존재 이유, 핵심 설계 결정의 근거, 개발 품질 기준을 정의한다. 새로운 기능을 만들거나 기존 구조를 변경할 때 이 문서의 원칙에 부합하는지 먼저 확인한다.

---

## 1. 왜 이 프로젝트를 만들었는가

**문제**: 개인 투자에서 감정과 직감에 의존하면 처분효과(Shefrin 1985)에 빠진다 — 수익 종목은 너무 빨리 팔고, 손실 종목은 너무 오래 잡는다.

**가설**: "왜 사야 하는지/팔아야 하는지"를 데이터로 증명하는 시스템을 만들면, 감정 개입을 제거하고 일관된 의사결정을 할 수 있다.

**핵심 차별점**: 추천을 내리는 것이 아니라, 추천의 근거를 증명하는 것이 목적이다.
- 20개 시그널 × 8,000+ 과거 트레이드 백테스트로 각 시그널의 승률/수익비(PF)를 검증
- 10개 에이전트가 독립적으로 분석한 뒤 가중 합의 (risk agent 거부권)
- SIEGE v2 gate (asset-class per-expansion) 가 모든 추천을 기계적으로 검증 — 1개 error-grade 라도 실패하면 REJECTED
- 5개 Plotly 차트가 최종 증거를 시각화

---

## 2. 설계 원칙

코드를 작성하거나 리뷰할 때 이 원칙을 적용한다.

### 2.1 증거 우선 (Evidence-first) — 3-tier bucket split

모든 BUY/SELL 판단은 **증거 품질에 따라 분류**된다. 숫자가 없을 때 "평균" 을 가정하지 않는다. 그런 가정이 사용자 손실의 원인이었다 (2026-04-17 codex audit 확인).

**Tier 정의** (`nuri/trading/recommend/candidates.py` `TIER_*` 상수)

| Tier | 조건 | 시스템 동작 |
|---|---|---|
| **actionable** | validated (≥ 30 trades) + positive edge (PF ≥ 1.0) | 정식 추천. confidence 수식 full 적용. UI 주요 리스트에 표시. |
| **advisory** | unscored (백테스트 미커버) OR low-sample (< 30 trades) | confidence = 0. 별도 section 에 disclosure 만. "참고만" 문구 필수. |
| **avoid** | validated 이지만 negative edge (PF < 1.0) | confidence = 0. 별도 section 에 "독립 행동 금지" 경고와 함께 노출. |

**규칙**
- 시그널 발생 → 해당 시그널의 scorecard 통계 조회 → tier 분류
- 통계가 없거나 negative edge 면 **추천 리스트에 섞지 않는다**. 투명하게 advisory/avoid 섹션에 노출.
- 에이전트 합의 → 각 에이전트의 판단 이유(reasoning) 기록. 통계 없는 agent 는 tier 와 별도로 specialization 표시 (`nuri/trading/agents/CLAUDE.md` 참조)
- 가격 타겟 → 매수가/손절가/익절가를 명시적 숫자로 제시. Tier 와 무관 (mechanical 규칙, §2.2)
- **"좋아 보여서"는 이유가 아니다.** 통계가 없으면 advisory 로만 노출하고, 추천으로 승격시키지 않는다.

**이전 framing 의 실패 모드 (2026-04-17 codex audit 에서 확인)**
- 원문 "숫자가 없으면 추천하지 않는다" 는 aspirational 이었으나 실제로는 `candidates.py:203` 에서 `win_rate=0.5, pf=1.0` 폴백 → confidence ~45 로 emit → user 입장에서 검증된 추천처럼 보였음. B-2 (PR 이번 Phase 1) 에서 제거.
- 또 다른 경로: SELL 시그널 통계 자체가 역방향 측정이라 positive 로 보였음 (모두 PF>1). B-1 에서 sign-flip fix 후 실제 PF 0.52–0.60 으로 드러남 → B-2-ext 에서 "avoid" tier 로 자동 분류.
- Learning Memory 동적 reweighting 은 현재 **dormant** (A-1 에서 부활 예정). 당분간 DEFAULT_WEIGHTS 정적 가중치로 동작.

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
- SIEGE certification: 조건 pass/fail 결과가 매번 기록됨 (count 는 가변 — §6 per-asset-class expansion 참조).
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

### 2.7 개발 Flow (gstack 7-phase, 2026-04-16 채택)

모든 작업은 **Think → Plan → Build → Review → Test → Ship → Reflect** 7단계를 통과한다. [gstack](https://github.com/garrytan/gstack) 의 Flow 를 nuri-quant 운영 discipline 으로 채택. 단계를 건너뛰지 않는다 (§5.9.7 Multi-role flow 강제의 refinement).

각 단계는 **입력 → 행동 → 산출물 → 통과 gate** 로 명세된다. Gate 를 통과하지 못하면 다음 단계로 넘어가지 못한다. 이전 "PM → Developer → Code Reviewer → QA → PR" 4-role flow 는 Think+Plan / Build / Review / Test / Ship 단계에 흡수됨.

| # | 단계 | 입력 | 행동 | 산출물 | 통과 gate |
|---|------|------|------|-------|-----------|
| 1 | **Think** | 사용자 신호 (이슈, 관찰, 페인포인트) | 문제 framing, root-cause, literature/dual 확인 (§2.1 Evidence-first) | GitHub 이슈 본문 또는 `docs/plans/*.md` 에 problem statement + evidence + constraint | "왜 **지금** 이걸 하는가" 를 한 문장으로 답할 수 있는가 |
| 2 | **Plan** | Think 산출물 | scope 정의, touched files, acceptance criteria, Escalation Ladder (§2.6) 레벨 선택 | PR description 초안 또는 `/plan` 출력 — 변경 파일 + 테스트 계획 + non-goals | 스코프 팽창 없는가? 이슈 1 = PR 1 준수? 커밋 ≤ 3 수렴 가능? |
| 3 | **Build** | Plan 산출물 | 최소 범위 구현. `config/*.yaml` 우선 (§2.2), DB-only phase 통신 (§2.3), `kst_now()` 강제 | feature 브랜치 커밋 | hardcode 없는가? hook/lint 통과? `git branch --show-current` 확인했는가? |
| 4 | **Review** | feature 브랜치 diff | Codex 독립 리뷰 (`/codex review`) + Claude self-review diff. P1 finding 해결 필수 | Review log, findings 목록, GATE verdict (PASS / FAIL) | P1 전부 해결? Claude ↔ codex disagreement 가 있다면 이유 명시? |
| 5 | **Test** | reviewed 브랜치 | `make test-fast` + **사용자 워크플로 live 실행** (§5.9.1 mock ≠ ship). UI 면 browser QA | green CI + manual QA 로그 (UI 스크린샷 또는 명령어 출력) | 사용자가 실제 입력할 명령을 1회 이상 직접 돌렸는가? |
| 6 | **Ship** | tested 브랜치 | `gh pr merge --squash --delete-branch`. 이슈 close. 로컬+원격 branch 정리. `docs/TODO.md` Tier 1 업데이트 | MERGED PR, CLOSED 이슈, Tier 1 entry, 깨끗한 `git branch -a` | Tier 1 행 추가됐는가? 브랜치 정리됐는가? |
| 7 | **Reflect** | ship 결과 | 무엇이 놀라웠는가? 새 gotcha? 메모리 업데이트? NEXT_SESSION refresh? | NEXT_SESSION.md 갱신 + 새 fix-pattern gotcha 는 STRATEGY gotchas 에 `**Test:**` cite (§5.3.1) + user memory 갱신 (해당되면) | 다음 세션이 이 작업 컨텍스트 없이 바로 뛸 수 있는가? |

**단계 실패 = 이전 단계로 회귀**. 예: Test 에서 mock-only 함정 발견 → Build 로 돌아가서 실제 경로 fix. Review 에서 P1 지적 → Build 로 돌아가서 fix. Reflect 에서 drift 발견 → Plan/Build 회귀 아닌 별도 chore PR 로 분리.

**Codex 부재 시 Review 단계**: Codex 사용량 한도 등으로 독립 리뷰가 막히면 Claude self-review diff 로 대체 + **다음 PR 의 Review 단계에서 회수** (이전 PR 을 함께 검토하도록 codex 에 cite). 무한정 지연하지 않는다.

**Think/Plan 생략 패턴**: trivial chore (오타, 버전 번호, 주석 수정) 는 Think/Plan 을 inline 으로 압축 가능. 단 Build 이상부터는 반드시 모든 단계 준수. "trivial 로 시작했지만 커짐" 을 Build 중 발견하면 Think/Plan 으로 회귀.

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
| Backend tests | 고정 minimum 없음 — Codecov 1% relative regression gate (목표 ≥ 95%) | 3,081 tests, 139 files |
| Frontend tests | 목표 ≥ 90% | 917 tests, 60 files |
| E2E | 핵심 flow 커버 | 39 Playwright tests (6 spec) |
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

**새 broker name 추가 시**: `scripts/check_privacy_leak.py`의 `BROKER_NAMES_KO` / `BROKER_NAMES_EN` 튜플에 추가. 테스트는 `tests/scripts/test_check_privacy_leak.py`. 이 표도 같이 갱신.

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
- 2026-04-14: #3 강화 ("실행한다" → "사용자 워크플로로 검증한다"), #7 추가 (외부 API 측정). Mock-only ship 함정 3회 반복 후 추가 (`docs/HARNESS.md §1` 참고).

### 5.9 Case Studies (on-demand reference)

실제 실패 세션의 구체적 교훈 (Mock-only 함정, 외부 API 동시성, ThreadPool 한계, JKHY falling knife 등) 은 `docs/HARNESS.md` 로 분리했다. 비슷한 패턴을 디버깅할 때만 참조. 본 STRATEGY §5 의 canonical 원칙 (§5.1-§5.8) 은 그대로 유지.

- `docs/HARNESS.md §1` — #272 세션 교훈 (2026-04-14, 12 PRs): Mock-only 테스트, API 동시성 비대칭, ThreadPool timeout 함정, 사용자 관점 검증, multi-role flow
- `docs/HARNESS.md §2` — JKHY 에피소드 (2026-04-14, PR #300-#303, #306, #307): dissent overwhelmed 실패 모드, mechanical divergence penalty, 초기 진단 오독 정정

---

## 6. SIEGE Gate 명세 (v2)

모든 추천은 아래 조건군을 통과해야 CERTIFIED 된다. 1개라도 **error 등급** 실패 시 REJECTED. Warning 은 경고 누적만.

**v2 변경 (PR #312, #248)**: 조건 개수는 **가변**. `certify()` 가 asset class (us_equity / kr_equity / kr_index / commodity / bond) 별로 5 / 7 / 8 조건을 per-class expansion 후 flatten. 고정 "11-gate" 명칭은 deprecated — v1 레거시 잔재로 `Certificate.total_conditions` 를 읽는 doc/코드가 있으면 v2 표기로 교정.

### Base 조건 (모든 asset class 공통)

| # | 조건 | 등급 | 기준 |
|---|------|------|------|
| 1 | position_limit | error | 단일 종목 비중. `config/rules.yaml account_strategies.<s>.per_position_max` — core 15%, active 25%, swing 30%, long_term 25%, pension 40% |
| 2 | sector_limit | error | 섹터 비중. `position_limits.max_sector_exposure` = 35% (top-level, 전략 공통) |
| 3 | stop_loss | error | 손절선 준수. 내부에서 종목 type (`config/stock_types.yaml` growth/value) 에 따라 threshold 분기. 전략별 override: `account_strategies.<s>.stop_loss` — core -7, active -10, swing -15, long_term -20, pension -30 |
| 6 | leverage_ban | error | 금지 ETF (`leverage.banned_tickers` 목록) 미보유 |
| 9 | conflict_free | warning | 동일 종목 BUY/SELL 충돌 없음 |
| 10 | drift_safe | warning | 매수 후보에 critical drift 시그널 없음 |
| 11 | macro_event_alignment | warning | \|event_score\| ≥ 10 시 경고 |

### Per-asset-class 조건 (v2 expansion — primary + secondary)

`config/rules.yaml siege_gates.asset_classes.<class>` 에 정의. 각 class 별 primary + secondary condition 이 flatten 된다.

| # | 조건 | 등급 | 출처 필드 |
|---|------|------|----------|
| 5 | data_fresh | warning | `freshness_primary` + `freshness_secondary[]` + `freshness_max_hours`. primary/secondary 각각 condition emit. |
| 7 | volatility_gate | warning | `volatility_primary` + `volatility_primary_threshold` (+ secondary). us_equity 는 VIX > 30, kr_equity 는 USD/KRW 3d change > 3% + VIX > 30 spillover, kr_index 는 KOSPI 3d > 5% + USD/KRW > 3% 등 |
| 8 | external_data | warning | `external_min_records` + `external_min_sources`. us_equity ≥ 10 / 3 source, kr_equity ≥ 5 / 2, kr_index/commodity/bond ≥ 3 / 1 |

### 예시 — us_equity 3종목 + kr_equity 2종목 포트폴리오

`certify()` flatten 결과 (2026-04-16 기준 실측):
- base 8 condition (#1-4, #6, #9-11)
- data_fresh: us primary(SPY) 1 + kr primary(KOSPI) 1 + kr secondary(SPY) 1 = **3**
- volatility: us(VIX) 1 + kr primary(USD/KRW) 1 + kr secondary(VIX) 1 = **3**
- external_data: us 1 + kr 1 = **2**
- **총 16 conditions**. 다른 포트폴리오는 다른 수치.

상세 per-class rule 은 `config/rules.yaml siege_gates` 와 `docs/SIEGE_V2.md` 참조. 실제 condition 생성 로직: `nuri/trading/engine/certification.py` `_check_freshness_for_class()`, `_check_volatility_for_class()`, `_check_external_for_class()` — 각 함수는 `list[CertCondition]` 반환, `certify()` 가 flatten.

---

## 7. 작업 정책

운영 backlog (Tier 1 완료 / Tier 2 next / Tier 3 research, 영구 배경 작업) 는 `docs/TODO.md` 로 분리했다. STRATEGY 는 **변하지 않는 정책** 만 담는다. 새 세션 시작 시 `NEXT_SESSION.md` → `docs/TODO.md` 순으로 확인.

### 7.1 자동 매매 — 영구 deferred (사용자 opt-out)

| 항목 | 이슈 | 결정 사유 |
|------|------|---------|
| Alpaca 실전 연동 (Paper → Live) | [#17](https://github.com/researcherhojin/nuri-quant/issues/17) | **영구 보류**. 2026-04-11 사용자 결정 — 자동 매매로 인한 손실 책임소재 이슈. 시스템 추천(확률적)과 실제 매매(결정적) 사이의 책임 경계가 모호해지는 걸 차단. |
| KIS Open API 한국 실전 매매 endpoint | — | **영구 보류** (동일 사유). `kis_realtime.py`의 **read** endpoint(잔고/가격/drift 모니터링)는 그대로 사용. 매매 endpoint만 연결하지 않음. |

**원칙**: 시스템은 추천과 알림에만 관여한다. 실제 주문은 사용자가 직접 증권사 앱에서 수동 실행한다. `DryRun` mode 및 paper trading 시뮬레이션은 백테스트/검증 용도로 계속 사용 가능.

이 결정을 뒤집으려면 STRATEGY.md 개정 PR + 명시적 재승인 필요.

### 7.2 작업 규칙 (PR discipline)

- **이슈 1개 = PR 1개**, 커밋 ≤ 3
- 새 발견 → 별도 이슈, 같은 PR에 묶지 않음
- Tier를 건너뛰지 않음 (Tier 2 시작 전 Tier 1 모두 close)
- 새 항목 추가 시 `docs/TODO.md` 를 함께 업데이트, 이슈 번호 필수

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
| [SIEGE Engine](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution) | Gate-based certification, event journal (외부 repo 는 11-gate v1, 본 프로젝트는 v2 asset-class expansion 으로 evolve) | `nuri/trading/engine/` |
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
