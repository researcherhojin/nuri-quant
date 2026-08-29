# Nuri-Quant 전략 정의서

이 문서는 프로젝트의 존재 이유, 핵심 설계 결정의 근거, 개발 품질 기준을 정의한다. 새로운 기능을 만들거나 기존 구조를 변경할 때 이 문서의 원칙에 부합하는지 먼저 확인한다.
<!--
Maintainer note: 이 파일은 `CLAUDE.md` 에서 `@docs/STRATEGY.md` 로 import 되어 launch 시 전량 context 에 load 된다. Claude Code 공식 가이드 ("target under 200 lines per CLAUDE.md", "imports do not reduce context") 에 따라 본문은 canonical policy + 결정의 "왜" 만 담는다. 상세 methodology / narrative / case study 는 별도 파일 (CERTIFICATION_SPEC.md, codex-reviews/, scripts/*.py docstring, git log) 에 위임한다. 이 원칙을 어기는 추가 narrative 는 stripped HTML comment 로 감싸거나 외부 파일로 뽑아내 context cost 를 0 으로 유지한다.
-->
---
## 1. 왜 이 프로젝트를 만들었는가
**문제**: 개인 투자에서 감정과 직감에 의존하면 처분효과(Shefrin 1985)에 빠진다 — 수익 종목은 너무 빨리 팔고, 손실 종목은 너무 오래 잡는다.
**가설**: "왜 사야 하는지/팔아야 하는지"를 데이터로 증명하는 시스템을 만들면, 감정 개입을 제거하고 일관된 의사결정을 할 수 있다.
**핵심 차별점**: 추천을 내리는 것이 아니라, 추천의 근거를 증명하는 것이 목적이다.
- 20개 시그널 × 8,000+ 과거 트레이드 백테스트로 승률/수익비(PF) 검증
- 10개 에이전트 독립 분석 후 가중 합의 (risk agent 거부권)
- SIEGE v2 gate (asset-class per-expansion) 기계적 검증 — 1개 error-grade 실패 시 REJECTED
- 5개 Plotly 차트가 최종 증거를 시각화
## 2. 설계 원칙
### 2.1 증거 우선 (Evidence-first) — 3-tier bucket split
모든 BUY/SELL 판단은 **증거 품질에 따라 분류**된다. 숫자가 없을 때 "평균" 을 가정하지 않는다 (가정 폴백이 과거 사용자 손실의 원인 — 2026-04-17 codex audit).
**Tier 정의** (`nuri/trading/recommend/candidates.py` `TIER_*` 상수)
| Tier | 조건 | 시스템 동작 |
|---|---|---|
| **actionable** | validated (≥ 30 trades) + positive edge (PF ≥ 1.0) | 정식 추천. confidence 수식 full 적용. UI 주요 리스트. |
| **advisory** | unscored (백테스트 미커버) OR low-sample (< 30 trades) | confidence = 0. 별도 section disclosure 만. "참고만" 문구. |
| **avoid** | validated 이지만 negative edge (PF < 1.0) | confidence = 0. "독립 행동 금지" 경고와 함께 노출. |
**규칙**: 시그널 → scorecard 통계 조회 → tier 분류. 통계 없거나 negative edge 면 추천 리스트에 섞지 않음 (advisory/avoid 섹션 노출). 가격 타겟은 tier 무관 mechanical (§2.2). "좋아 보여서" 는 이유가 아님 — 통계 없으면 advisory.
과거 실패 모드 (archived 2026-04-17):
- `candidates.py:203` win_rate=0.5, pf=1.0 폴백이 confidence ~45 로 emit (B-2 에서 제거)
- SELL 시그널 역방향 측정 bug 로 모두 PF>1 (B-1 sign-flip fix 후 0.52–0.60 로 드러남, B-2-ext 에서 avoid 자동 분류)
- Learning Memory warming up: recommendations.agent_verdicts 144 rows 누적, strategy_memory 스냅샷은 outcome_30d 채워진 후 생성 → 첫 weight drift ~2026-05-17 예상 (TODO.md Tier 1 row 20). 그 전까지 DEFAULT_WEIGHTS 정적.
### 2.2 기계적 실행 (Mechanical execution)
규칙은 `config/rules.yaml` 에 정의, 코드는 실행만.
- 손절 -7%(성장)/-10%(가치), 익절 +20%/+40%, 트레일링 -15% — 예외 없음
- VIX > 30 신규 매수 차단 — "이번엔 다르다" 불허
- SIEGE gate 실패 → REJECTED, 수동 오버라이드 없음
- **execution_priority** (PR #200): 손절 → 익절 → 트레일링 설정 → 신규매수. 출혈 차단이 수익 확정보다 선행. 손절 내 손실률 큰 것부터, 익절 내 타겟 초과율 큰 것부터.
- 규칙 변경은 YAML 수정 + 백테스트 검증. 코드에 예외 분기 금지.
### 2.3 느슨한 결합 (Loose coupling via data)
파이프라인 5개 스테이지는 **가능한 한** DB/CSV 로 통신한다. 원칙은 유지하되, 여기 적힌 것은 실측이다 (#920/#922 — 이전 문구 "8개 페이즈는 서로 import 하지 않는다"는 거짓이었고, 스테이지→디렉터리 매핑이 없어 검증조차 불가능했다).
- **이유**: 앞 스테이지 재실행 시 뒤 스테이지가 자동으로 새 데이터 사용. 직접 import 하면 실행 순서/상태 관리 복잡.
- **스테이지 매핑** (검증 가능성의 전제): `collect`=`nuri/collectors` · `analyze`=`nuri/analysis` · `consensus`=`nuri/trading/agents` · `certify`=`nuri/trading/engine` · `track`=`nuri/trading/recommend`. `nuri/quant`·`nuri/core` 는 공용 라이브러리이지 스테이지가 아니다.
- **원칙**: 새 모듈은 다른 스테이지 함수를 직접 호출하지 않는다. DB 테이블/CSV 로 전달.
- **실제로 강제되는 것**: 교차 import 는 **함수 본문 안(deferred)에만** 허용 — module-level 금지 — 이고 사유와 함께 allowlist 에 등재해야 한다. 실측 **17건 / 15 pair / module-level 0**. `engine/conflicts.py` ↔ `recommend/candidates.py` 상호 의존은 deferral 덕분에만 로드되며, 하나라도 hoist 하면 import 가 깨진다.
- **예외 2건**: 같은 스테이지 내부 import 허용. consensus→certify 핸드오프는 `scheduler.py` 가 객체를 **메모리로** 넘긴다 (DB 경유 아님).
- **Test**: `tests/core/test_cross_stage_imports.py` — 신규 교차 의존과 사라진 allowlist 항목 **양방향** 모두 FAIL.
### 2.4 관찰 가능성 (Observability)
모든 상태 변화는 추적 가능해야 한다.
- `pipeline_events` 테이블: append-only event journal. `causation_id` 로 이벤트 체인 추적.
- Freshness SLA: 데이터 소스별 warn/fail 임계값. PASS 아니면 대시보드 경고.
- SIEGE certification: 조건 pass/fail 매번 기록 (count 가변 — §6 per-asset-class expansion).
- **새 기능 기준**: "이 기능이 실패하면 어떻게 알 수 있는가" 를 먼저 답한다.
### 2.5 비용 최소화 + 데이터 sovereignty (Lean-cost stack)
유료 API / 클라우드 / 상용 소프트웨어 의존을 최소화한다. 100% 무료 교조 아님 — quality 향상이 정량화되고 연 비용이 이자 한 잔 수준이며 §4.4.3 sovereignty 룰을 지킬 수 있을 때 도입 허용.
| 선택 | 이유 |
|------|------|
| SQLite (not Postgres) | 별도 서버 불필요. WAL 모드 동시 읽기. `tmp_path` 테스트 격리. |
| **Hybrid LLM stack** | 공개 RSS 분류 / 일간 리포트 → OpenAI `gpt-5.4-nano` (Tier 0 / Tier 2 ZDR). 사용자 narrative (Tier 1) 미허용. 로컬 LLM (Ollama / LM Studio 로컬 모델) 은 **on-demand only — 상시 가동 폐지 (2026-07-08, #854)**: 매매 파이프라인은 ZERO-LLM 이라 기여 0, 유지비용만 실재. sovereignty (§4.4) 는 불변. 상세 §4.4.3. |
| OpenBB + yfinance | 무료 데이터. OpenBB provider 교체 용이, yfinance 폴백. |
| GitHub Actions | 오픈소스 무료. lint + test + coverage + security 자동화. |
### 2.6 Escalation Ladder (근거 기반 → 기계적 개입의 4단계)
§2.1 (Evidence-first) 과 §2.2 (Mechanical) 는 같은 스펙트럼의 양 끝. 모든 증거에 대해 어디까지 기계적으로 개입할지는 4단계 사다리로 결정. **3 단계는 downside-block, 1 단계는 upside-amplify**. 새 feature 설계 시 레벨을 명시적으로 고르고 PR/STRATEGY 에 기록.
| 단계 | 방향 | 행동 | 언제 | 예시 |
|------|------|------|------|------|
| **Surface** | — | 증거 노출만 (UI/reasoning/log). action·confidence 불변. | noisy, sparse, outcome-검증 부족. 판단 여지 유지. | PR #301 `divergence_flag`, PR #302 UI 배지 |
| **Soft penalty** | down | 결정적 downgrade/reweight (HOLD 전환, confidence cap). 차단 아님. config tunable. | 같은 반대 시그널 반복 + downside skew 명확, universal fatal 은 아님. | PR #303 `divergence_technical_threshold` (default 80) |
| **Hard veto** | down | action 강제 변경 또는 차단. config 건드리기 어렵게. | 정책 수준, risk-of-ruin 급. | Risk agent 거부권, execution_priority, VIX>30 차단 |
| **Symmetric amplifier** | up | Post-veto sizing — veto/penalty 통과한 eligible candidate 에 대해서만 다중 favorable 조건 동시 충족 시 size/confidence 상향. cap 강제 (baseline × 1.5). | regime + momentum + VIX 모두 favorable. 단일 조건 발동 금지. | E3 도착 예정 (§3.6) |
**운용 원칙**:
1. Surface → Soft penalty 이관은 **데이터 기반** (발동 빈도 + 적중률 측정 선행, `pipeline_events` 의 `consensus_penalty_applied` 감사).
2. Soft penalty → Hard veto 이관은 **정책/이론 기반** (STRATEGY 개정 PR + 백테스트).
3. 등급 상향은 쉽고 하향은 어렵다 (mechanical → informational 시 과거 case 해석 모호).
4. **Amplifier 평가 순서**: 항상 veto/penalty 이후. Hard veto 차단 candidate 는 amplifier 대상 아님 — 보상 증폭이 손실 회피 우회하는 경로 구조적 불가능. 발동 전 Surface 단계에서 측정 (§3.6 minimum sample/positive-outcome).
5. **승격 게이트 — champion-challenger 순차 통제 (#1307, 2026-08-29)**: 투자 룰 변형(challenger)의 승격 자격 판정은 `nuri/quant/validation/champion_gate.py` 를 거친다. 한 캠페인 안의 다중비교는 기존 walk-forward gate(Bonferroni + frozen holdout, #706)가 통제하고, **캠페인을 거듭하는 순차 탐색**은 이 게이트가 통제한다 — (a) 기각 포함 모든 시도를 `challenger_attempts` 원장에 기록(#1305 evidence 바인딩 포함, append-only), (b) 캠페인 j 의 alpha 배정 = `alpha_total / 2^j` 반감 스펜딩(무한 반복해도 family 평생 예산 불변), (c) 같은 holdout 세대는 `holdout_max_uses` 회 열람 후 은퇴 — 재사용된 봉인 구간은 봉인이 아니므로, 이후는 새 `holdout_version` 사전등록 PR 전까지 승격 제안 불가. 파라미터는 `config/walkforward.yaml champion_gate:` (변경 = STRATEGY PR). **기계는 기각만 자동이다** — `promotion_candidate` 는 제안이고 승격은 항상 사람의 STRATEGY PR (운용 원칙 2 와 동일 축). 증거 축 분리: 이 게이트는 research(walk-forward) 전용 — §3.11 라이브 결정원장 판정과 한 verdict 안에서 섞지 않는다 (승격 서사가 유리한 축을 골라 쓰는 것을 막는다).
**Anti-pattern**: Surface 과용 → "performative 경고" (JKHY ⚠ 배지 행동 무변화). Hard veto 과용 → 기회 손실 + 판단권 박탈. Amplifier 를 Soft penalty 대칭 mirror 로 단일 조건 발동 → noise pumping. **변경 절차**: 단계 이동은 config/docs PR 로. 코드 매직넘버 금지.

**게이트 입력이 없을 때 (2026-08-10 채택)** — 사다리는 시그널이 *있을 때* 무엇을 하느냐만 규정했고, 입력이 **없을 때**는 침묵했다. 그 공백을 `buy_candidate_emitter._get_regime` 이 `vix = 20.0` 으로 메우고 있었다. 20.0 은 차단(>30)·caution(≥25) 임계 **아래**라 측정 불가가 조용히 통과권을 얻었고, 브리핑에는 `VIX=20.0` 이 측정값처럼 찍혔다. #753 이 같은 계열(미수집 `prices.VIX` 를 읽어 항상 폴백)로 이미 한 번 게이트를 무력화한 기록이다.

원칙: **위험 게이트의 입력 부재는 그 게이트의 가장 보수적 관측치와 같은 등급으로 처리한다.** VIX 미상·노후(`entry_rules.vix_gate.max_age_business_days`, 기본 **영업일** 2일 — 달력일로 재면 휴장 뒤 정상 데이터가 미상으로 떨어진다)는 caution 구간과 동일한 **Soft penalty**(절반 포지션)다. Hard veto 로 올리지 않은 이유는 수집 하루 장애로 강세장 진입 기회를 통째로 잃는 비용이 실측되지 않았기 때문이고, Surface 로 낮추지 않은 이유는 근거 없이 전액이 나가는 것이 §2.6 이 막으려는 바로 그 형태이기 때문이다. 표기는 숫자가 아니라 `미상` — 없는 측정을 있는 것처럼 적지 않는다.

**점수 성분에는 다른 규칙이 적용된다 (2026-08-10)** — 위 조항은 *게이트*(통과/차단) 이야기다. `factors/composite` 의 센티먼트처럼 **점수 성분**이 없을 때는 "가장 보수적 관측치" 라는 게 정의되지 않는다. 그때는 값을 지어내지 말고 **성분을 빼고 나머지 비중을 비례 재정규화**한다(합계 1.0 유지). 과거엔 Fear & Greed 부재 시 `0.5` 를 채웠는데, 0.5 는 중립이라 무해해 보여도 실측 0.637 대비 0-100 스케일에서 2.74점이고 `quality_bar.base_threshold: 70` 앞에서 통과 **개수**를 움직였다. 재정규화는 "모른다" 가 점수를 위로도 아래로도 밀지 않게 한다. 랭킹은 어차피 불변이다 — 시장 전체 값이라 모든 티커에 같은 양이 들어간다.

**2차 적용: `regime/macro_score` (2026-08-11, #1026)** — 같은 조항을 9성분 매크로 점수에 적용했다. 결측 성분에 `50.0` 을 채워 가중합하던 것을 **성분 제외 + 비례 재정규화**로 바꾸고 `coverage`(측정된 가중치 합)를 함께 내보낸다. 실측 여파가 크다: `FRED_API_KEY` 미설정으로 FRED 전용 지표 **8개 전부 0행**이라 3성분(3M-10Y · 실업 · CPI)이 결측이고, 총점 **64.4 "Neutral" → 71.3 "Favorable"** 로 **해석 경계를 넘는다**. 지어낸 중립이 우호적 판독을 눌러 온 것이다. 코드는 이미 결측을 감지해 `warnings` 에 담고 있었으나 **읽는 소비처가 0개**였다 — 감지는 어디에도 닿지 않으면 없는 것과 같다. 얇은 표본이 확신 라벨을 달지 않도록 `macro.min_coverage`(기본 0.6) 미만이면 `interpretation="Insufficient"`.

**SIEGE 게이트에도 같은 원칙이 적용된다 (2026-08-10, #1022)** — §6 gate 7 `volatility_gate` 는 지표가 없으면 `passed=True, "데이터 없음 — 스킵"` 을 냈다. 이 게이트의 가장 보수적 관측치는 **자기 자신의 실패 상태**(warning)이므로, 입력 부재는 `passed=False, severity=warning` 으로 낸다. 적용 범위는 게이트의 **판정 입력**(primary)이다 — 보조 spillover 지표(secondary)는 값이 없으면 condition 을 아예 만들지 않아 "정상" 이라 주장하지도 score 를 부풀리지도 않으므로 그대로 둔다. 없는 참고 지표마다 경고를 띄우는 건 §2.6 이 경계하는 performative 경고 쪽이다. 영구 미수집 secondary 는 런타임이 아니라 PR 시점 계약 테스트가 잡는다. 30줄 위 `data_fresh` 는 처음부터 그렇게 동작했다 — 같은 파일 두 게이트가 같은 상황에 반대로 답하고 있었다. warning 이라 `certified` 는 안 막는다 — **매매 행동은 안 바뀐다**(Surface rung). 다만 "무변화" 는 아니다: `score = passed/total` 이라 인증서 점수가 내려가고, 그 값은 `certifications` 테이블에 적재돼 `/api/engine` 이 rolling 평균을 낸다. 즉 **이 커밋 앞뒤의 score 시계열은 정의가 달라 직접 비교하면 안 된다** (실측 63 → 56). 이전 구간이 높았던 건 개선이 아니라 평가되지 않은 게이트를 통과로 세었기 때문이다. E4-0b predictivity 감사가 이 경계를 넘는 구간을 쓸 때 반드시 분리할 것. 실측 여파: `kr_index` · `bond` 의 primary 지표(`kospi` / `yield`)는 프로덕션 `macro` 에 n=0 이라, 두 게이트는 도입(#248) 이래 한 번도 평가되지 않은 채 매 인증서에 초록으로 찍혀 있었다. **미수집이 아니라 배관 문제다** — `prices.KOSPI` 는 419행 있고 같은 인증서의 freshness 게이트가 이미 그걸 읽는다. 변동성 게이트만 `macro` 전용 경로라 못 볼 뿐이다. 그래서 이 PR 은 semantics 만 고치고(거짓말 제거), 입력 경로 연결과 bond threshold 재도출은 분리한다 — 후자는 `_compute_3d_change` 가 pct 를 돌려주는데 threshold 0.3 은 bp 의미로 쓰여 있어 포인터만 바꾸면 죽은 게이트가 상시 발화 게이트로 바뀐다.

이 조항에 백테스트를 붙이지 않는다. 발동 조건이 시장 시그널이 아니라 **데이터 장애**라, "VIX 가 없었다면" 을 과거 시장에 되돌려 세우는 것은 의미 있는 증거가 아니다. 등급을 올리거나 내리려면 실제 장애 발생 빈도와 그때의 시장 분포를 먼저 측정할 것.
### 2.7 개발 Flow (gstack 7-phase, 2026-04-16 채택)
모든 작업은 **Think → Plan → Build → Review → Test → Ship → Reflect** 7 단계. 단계 건너뛰지 않음. Gate 통과 못 하면 다음 단계 못 감.
| # | 단계 | 입력 | 행동 | 산출물 | 통과 gate |
|---|------|------|------|-------|-----------|
| 1 | **Think** | 이슈/관찰/페인포인트 | 문제 framing, root-cause, literature 확인 (§2.1) | 이슈 본문 또는 `docs/plans/*.md` problem + evidence + constraint | "왜 지금" 을 1 문장으로 답 가능? |
| 2 | **Plan** | Think 산출물 | scope, touched files, acceptance, Escalation Ladder (§2.6) 레벨 | PR description 초안 / `/plan` 출력 | 스코프 팽창 없는가? 이슈 1 = PR 1? 커밋 ≤ 3? |
| 3 | **Build** | Plan | 최소 구현. `config/*.yaml` 우선 (§2.2), 교차 스테이지 import 는 deferred + allowlist (§2.3), `kst_now()` 강제 | feature 브랜치 커밋 | hardcode 없는가? hook/lint 통과? `git branch --show-current` 확인? |
| 4 | **Review** | feature diff | Codex `/codex review` + Claude self-review. P1 해결 필수 | Review log, GATE verdict | P1 전부 해결? disagreement 이유 명시? |
| 5 | **Test** | reviewed 브랜치 | `make test-fast` + 사용자 워크플로 live 실행 (§5.9.1). UI 면 browser QA | green CI + manual QA 로그 | 사용자 명령 1 회 이상 직접 실행? |
| 6 | **Ship** | tested 브랜치 | `gh pr merge --squash --delete-branch`. 이슈 close. branch 정리. TODO.md Tier 1 업데이트 | MERGED PR, CLOSED 이슈, Tier 1 entry | Tier 1 추가? 브랜치 정리? |
| 7 | **Reflect** | ship 결과 | 놀라웠던 점, 새 gotcha, 메모리 업데이트, NEXT_SESSION refresh | NEXT_SESSION 갱신 + fix-pattern gotcha 는 `**Test:**` cite (§5.3.1) | 다음 세션이 바로 뛸 수 있는가? |
**단계 실패 = 이전 단계 회귀**. Codex 부재 시 Claude self-review + 다음 PR Review 에서 회수. Trivial chore 는 Think/Plan inline 압축 가능 (Build 이상은 모든 단계 준수).
**Next-session entry artifact Plan gate** (2026-04-22): `NEXT_SESSION.md` 는 docs-only/gitignored 라도 Reflect 산출물. **Inline OK**: typo/format/self-note/HEAD append. **Plan consult 필수** (다음 primary PR 의 Plan consult 에 batch 포함): next primary 변경, 우선순위 재정렬, risk framing 신규, live command 교체, acceptance 변경. Re-consult trigger: (a) next primary 변경, (b) 후보 2+ 경쟁, (c) handoff stale 가능성, (d) 5 PR 누적 또는 48h burst 후 cadence reflection, (e) legal/TOS/production-risk 신규.
Burst ship cadence (2026-04-22 실측, 48h 6 functional + 3 docs PR): 재현 조건은 독립 scope + 명확한 queue + codex Plan consult 선행. Sustainable default 아님 — codex Round 2 skip 빈발, docs PR scope-discipline 경계, reviewer fatigue, handoff drift. 48h 이상 burst 후 반드시 handoff Plan consult + 다음 cycle cadence 내림.
## 3. 핵심 아키텍처 결정 기록
향후 이 결정을 변경하려면, 아래 "이유" 를 반박할 근거가 필요하다.
### 3.1 DB 가 유일한 통합 지점
`nuri/core/db/` 만 `sqlite3` import. 다른 모듈은 `query()`, `query_df()`, `upsert_*()`, `get_db()` 만 사용.
**이유**: DB 접근 패턴 단일 제어 → WAL 충돌 방지, 트랜잭션 관리, 마이그레이션 안전. 테스트에서 `db_path` 주입으로 완전 격리.
### 3.2 10-에이전트 가중 합의
10 개 에이전트 독립 분석 + 가중치 투표. Risk agent 거부권 (SELL + confidence ≥ 80 → 전체 오버라이드).
**이유**: 단일 모델 편향 감소. 손실 회피가 수익 추구보다 우선.
**가중치**: `config/agents.yaml`. Learning Memory 가 과거 적중률로 ±30% 범위 동적 조정.
### 3.3 Confidence 스코어링 파이프라인
```
base = regime_win_rate × 60% + profit_factor × 40%
     × drift_multiplier (0.3 ~ 1.1)        ← Learning Memory
     × conflict_penalty (0.5x if high)     ← Conflict Detection
     × regime_fit_penalty (0.4x if avoid)  ← Strategy Map
     × position_penalty (0.3x if minimal)  ← Regime position sizing
     × vix_gate (0x if blocked, 0.5x caution)
**이유**: 단순 승률 부족. 현재 레짐 성과, drift, 충돌 여부 모두 반영해야 신뢰도 있는 점수.
### 3.4 투자 규칙의 출처
모든 규칙에는 학술/실증 근거가 있다. 근거 없는 규칙 추가 금지.
| 규칙 | 근거 | 출처 |
|------|------|------|
| 손절 -7% | CAN SLIM + 자체 validation PR F (2026-04-22). us_core 85 × SMA golden cross 250 entries paired counterfactual: ATR shadow surface 는 6-metric 3/6 로 acceptance 미달 → **PR F2 deferred**, -7% 유지. 상세: `scripts/episodes/pr_f_atr_validation.py` docstring + commit `c834049`. | O'Neil, *How to Make Money in Stocks* |
| 익절 +20%/+40% | 손익비 3:1 유지 | Minervini, *Trade Like a Stock Market Wizard* |
| 트레일링 -15% | 11년 백테스트 최적 (73.9% 누적) | 자체 백테스트 |
| VIX > 30 매수 차단 | 공포 구간 승률 붕괴 검증 | 자체 시그널 백테스트 |
| 슈퍼투자자 ≥ 3명 | 13F 보유 종목 초과수익 | SEC EDGAR 분석 |
| 처분효과 경고 | 수익 조기 매도 편향 | Shefrin & Statman, 1985 |
| **execution_priority** | 하락 모멘텀 1h 지연 = 추가 손실 확정 | 자체 재무 논리 (PR #200) — ⚠️ **미배선**: config 를 읽는 코드 없음 (§3.5 주석) |
| **trailing_stop_arm +15%** | 수익 give-back 방지 | PR #202 — ⚠️ **미배선**: 트레일링은 무장 조건 없이 HWM 기준 동작 (§3.5 주석) |
| **decisions 결과 추적** | 에이전트별 적중률로 가중치 동적 조정 | PR #181, #183 |
| **Kelly f\* = (bp−q)/b** | edge·승률·payoff 반영 position size. Fractional Kelly (full 은 estimation error·DD 로 부적합). E3 실배선. | Kelly (1956); MacLean/Thorp/Ziemba (2011) |
| **Mean-variance frontier** | sector cap 의도. `max_sector_exposure: 35%` 는 frontier 도출 아닌 prudential default. regime 재평가 E3 후보. | Markowitz (1952) |
| **Trend-following regime filter** | 장기 SMA risk-on/off 전환. §3.6 empirical 출발점. | Faber (2007) |
### 3.5 계좌별 전략 프로파일
`config/rules.yaml account_strategies` 에 정의. `portfolio.yaml` 의 계좌 `strategy` 필드와 매칭.
| 전략 | 손절 | 단일종목 | 섹터 | 특이사항 | 의도 |
|------|------|--------|------|---------|------|
| **core** | -7% | 15% | 35% | — | 정석. Main 기본값 |
| **active** | -10% | 25% | 45% | `trailing_stop_arm: 15` | 손실 짧게, 수익 길게 (PR #202) |
| **swing** | -15% | 30% | 50% | — | 단기 5~20일 |
| **long_term** | -20% | 25% | 50% | — | 장기 보유 |
| **pension** | -30% | 40% | 60% | — | 연금 ETF 초장기 |
**선택**: Core 보수, Active 적극 컷+위너보호, Swing 진짜 단기, Long_term/Pension 장기 ETF. 규칙 변경은 YAML + 백테스트 + PR.

> ⚠️ **위 표 중 실제로 강제되는 건 손절과 단일종목 한도뿐이다 (2026-08-02 감사).**
> - **섹터 열은 장식이다.** `account_strategies.*.max_sector_exposure` 를 읽는 코드가 없고, 섹터 검사(certification · rebalance_advisor · execution_firewall)는 전부 전역 `position_limits.max_sector_exposure`(35%)를 쓴다. 즉 pension 계좌를 60%로 적어둬도 35%에서 걸린다.
> - **`trailing_stop_arm: 15` 도 읽는 코드가 없다.** 트레일링은 존재하되 계좌별도 아니고 무장 조건도 없다 — `check_trailing_stop_signals()` 가 보유 전 종목에 대해 진입 후 고점(HWM) 대비 하락으로 판정한다(-15% growth/value, -20% volatile/swing). "+15%에 도달해야 켜진다"는 서술은 사실이 아니었다.
>
> 배선하는 건 매매 동작 변경이라 별도 STRATEGY PR 대상이다. 지금 이 문단은 **문서를 코드에 맞춘 것**이지 규칙을 약화시킨 게 아니다.
### 3.6 Regime-adaptive framework (E3)
**상태 (2026-04-29)**: Phase 1 shadow shipped (#479). **Phase 2 paired counterfactual: FAIL by binary rule** — 30d horizon CI_lower=-1.06% ≤ 0. 60d/90d horizons는 robust PASS (CI_lower=+1.95% / +2.60%). 자세히 아래 "Phase 2 verdict" 참조. **Phase 3 영구 보류 (2026-04-29 3-LLM consensus)** — Codex(gpt-5.4) Round 1 B → Round 2 A, Qwen3.5-122B Round 1 D → Round 2 A, Claude A 일관. Phase 1 shadow telemetry 영구 유지 (`enabled: false`, 무기한). Reopen trigger: §7.1 auto-trade reversal only. 자세한 Round 1/2 verdicts: `data/llm_consults/2026-04-29_e3-phase2-shelve-decision.md` + `..._round2-three-way.md` (gitignored, 사용자 머신 local).
**Phase 2 verdict (2026-04-29, branch `feat/e3-phase2-paired-counterfactual`)**:
- Spec: `docs/plans/E3_phase2_paired_counterfactual.md` (post Round 5 codex GATE PASS)
- Universe: us_core 85 frozen (81/85 with ≥1000 price rows), 2020-01-01+
- Gate: `recovery_confirmed AND vix_favorable(VIX<22 AND 3d_slope<0) AND regime_favorable(in {bull_low_vol, recovery} AND conf≥0.60)`. macro_benign dropped — no 5Y backfill.
- Sample: 14,728 raw 20d-breakouts → 166 eligible (post-90d-window) on 7 unique trading days. Effective N≈7 (binding power-limit caveat).
- Bootstrap: 1000 iter × block_size=20 trading days (frozen primary), seed=42.
- Metrics:
| Horizon | N | Mean Δ | CI95 Lower | CI95 Upper | Verdict signal |
|---------|---|--------|-----------|-----------|----------------|
| **30d (primary)** | 166 | +0.54% | **−1.06%** | +2.59% | **FAIL** |
| 60d | 166 | +4.46% | +1.95% | +7.75% | (would PASS) |
| 90d | 166 | +6.76% | +2.60% | +12.53% | (would PASS) |
- Sensitivity (block 10/40 informational): 60d/90d remain robust PASS across all block sizes; 30d remains FAIL.
- Decision: **FAIL** by spec acceptance rule (PASS iff 30d CI_lower > 0).
- Honest framing: amplifier effect is real and large at 60d/90d but power-limited at 30d.
- **Final disposition (2026-04-29 3-LLM consensus)**: Phase 3 (alpha-amplified live) **permanently shelved**. Decisive argument: §7.1 auto-trade is permanently deferred → E3 effect path collapses to conf-boost-only on recommendations, which user manual judgment already moderates → Phase 3 의 product value chain 이 broken. Redesign options (a/b/c/d) 모두 **각하** — (a) sample extension은 effective N≈7 power-limit 미해결, (b) universe widening은 survivorship bias trade-off 가 conf-boost-only 가치에 비해 과함, (c) regime threshold 완화는 result-fitting risk, (d) macro_events 누적 후 재시도는 §7.1 deferral 이 product-layer 답을 안 바꿈. **Spec amend (D-style 30d→60d primary) 거부** — 5-round GATE PASS 후 사후 amend 는 process credibility 훼손. 60d/90d PASS 는 "supportive horizon evidence" 로만 기록 (Phase 3 promotion 근거 아님).
- **Reopen trigger**: STRATEGY §7.1 reversal (auto-trade 재개) 결정 시에만. 그 시점에 fresh spec 재작성 (real execution path tied) 후 Phase 2 재실행.
- Phase 1 shadow telemetry 영구 유지: amplifier `enabled: false` 무기한, gate evaluation 만 logging.
- Verdict artifact: `data/reports/<YYYY-MM-DD>/e3_phase2_verdict.json` (gitignored).
- Lock-tests: `tests/quant/exits/test_amplifier_paired_replay.py` (24 invariants), `tests/quant/exits/test_amplifier_stage0_audit.py` (13 invariants).
**원래 framework intent**: §3.4 Kelly·Markowitz·Faber + §2.6 Symmetric amplifier 를 config + code 로 배선. `siege_gates.regime_overrides` 스키마 + `certification.py` 분기. **Hard veto (VIX>30, risk-of-ruin) override 금지**.
**E3 acceptance (2026-04-19 codex Plan consult)**: 3-stage validation — **Stage 0 + Stage 2 모두 통과 시 ship** (Stage 1 진단 신호). 순서: Stage 0 → 1 (병행) → 2.
- **Stage 0 — No-lookahead audit**: classifier historical 호출 시 future row 가 rolling stats 에 유입되지 않음 검증 (`compute_dynamic_thresholds()`, `_load_spy_series()`, special-regime detectors, `classify_regime_history()` intra-month flip 은닉 점검).
- **Stage 1 — Classifier plausibility (diagnostic)**: N=24~36 date 샘플 → regime label → forward 30d return 분포 directional sanity. fail 해도 Stage 2 PASS 시 ship (codex Round 1 P1: raw sign predictivity 없어도 sizing rule 은 loss attenuation 가치).
- **Stage 2 — Paired counterfactual (main gate)**: Frozen entry signal 단일 source (후보: SMA crossover / momentum top-decile / BUY signal historical replay). prices 5Y × N≥200 entries. (a) baseline vs (b) regime-adaptive sizing → forward 30/60/90d return. **Same entries, only sizing differs**.
**Primary metrics** (Sharpe 가 아닌 paired — 50-200 sample 로 Δ0.1 detect power 부족): mean paired excess return 30/60/90d, bootstrap CI on mean/median paired delta, downside rate / MAE, CVaR / drawdown, sign test (보조).
**Secondary (deferred)**: walk-forward 5Y IS / 1Y OOS Sharpe+DD, Monte Carlo regime mis-classification 5%.
**Amplifier 발동 조건**: Surface 20+ 발동 중 70%+ positive outcome (paired excess return > 0 at 30d) 누적 후 승격.
### 3.7 SIEGE 의 한계와 equity-context 재평가 (E3 가설)
**라벨**: hypothesis for E3 validation. 진단 유효 — "upside / opportunity-cost gate 0개". 정량 acceptance 는 §3.6.
**진단** (2026-04-18, `certification.py:553`): `ALL_CERT_CHECKS` 11 base (portfolio 구성에 따라 11~30+ 가변) 가 **모두 downside-block** — position/sector cap, stop-loss, leverage ban, freshness, volatility, external, conflict, drift, macro, rules. **upside / opportunity-cost gate 0**. 결과: "신규 매수 안전한가" 만 판정, "현금 보유 기회비용" invisible. VIX 12 + bull + momentum top-decile favorable 합치에도 silent. 사용자 페인 ("너무 보수적") 구조적 원인.
**업데이트 2026-04-21 (PR A #429)**: "SIEGE REJECT → 매도 surface" 경로는 structural fix shipped. §2.6 Soft penalty 구현 — concentration/sector_limit 은 `portfolio_action=REBALANCE` 로 분리, alpha (SELL) 경로 차단. Live verify (production DB): BAC/TSLA concentration → `portfolio` bucket, urgent 0. **원 진단 (upside gate 부재) 은 여전히 open** — PR A 는 "downside-only 의 잘못된 increase-risk emit" 만 막음.
**업데이트 2026-04-22 (§3.8)**: "downside-block 방향" 은 structural truth 이나 "effectively downside-predictive 로 작동" premise 는 synthetic audit 에서 tentatively refuted (position_limit Δ wrong-sign 반복). Prudential constraint 로 유효, predictive gate 로는 미증명. upside-gate 논의 시 "기존 gate 가 intended 대로 작동" assumed 로 두지 말 것.
**가설** (E3 에서 검증, §3.6 3-stage): §2.6 4번째 rung (amplifier) + §3.4 Kelly/Markowitz/Faber 근거 위에서 SIEGE 양방향 균형 (REJECT 외 favorable 측정) 도입이 baseline 대비 paired outcome 개선하는가. Amplifier 와 Hard veto 충돌 우선순위는 §2.6 운용 원칙 4 (post-veto sizing).
**경고**: 본 §3.7 진단·가설을 prescriptive 로 인용해 config/code PR 만드는 것 금지. §3.6 백테스트 PASS 전까지 hypothesis 등급. PR A #429 는 예외 아님 (alpha/portfolio 데이터 구조 분리만 shipped, upside gate 추가 아님).
### 3.8 SIEGE predictivity measurement (E4-0b v2) — audit route closed
**상태**: v1 #417 → v2 재설계 → 60-month production rerun 완료 (2026-04-22, Mac mini). 결과: acceptance `CI_upper < 0` 미달, `position_limit` Δ point estimate 반복 wrong-sign (fired > not_fired, 30/60/90d 전부). **variant ladder × momentum-based snapshot audit route 는 2026-04-22 data/design 에서 §3.7 downside-predictive framing 을 증명하지 못함 — closed**. §3.7 hypothesis 전체가 closed 된 것 아님 (real-portfolio replay, `recommendations.outcome` 누적, Symmetric amplifier 전용 측정은 열림).
**Prudential vs predictive 축 분리 (필수 인용 규칙)**: `position_limit` / `sector_limit` / `leverage_ban` 는 **prudential portfolio constraints + user-preference defaults** 로 유효 — 감정 통제, §7 자동 매매 deferred, O'Neil/Minervini lineage. **그러나 synthetic audit 은 forward-downside-predictive gate 로 기능한다는 주장 미증명**. 혼동 금지 — rule 은 prudential 근거로만 인용, downside-predictive framing 은 §3.8 에서 tentatively refuted.
**E4-0c (measurement consume 후 재-grading) 무효화** — consume 할 durable evidence 없음. §3.7 upside-gate hypothesis 는 §3.6 paired counterfactual (sizing-rule legitimacy, E3-3b PASS) 과 별도 경로로 검증 (user actual portfolio replay, `recommendations.outcome` 누적 후 real-history).
**상세 methodology / gate eligibility matrix / 60-month gate-level table / deferred extensions / 재실행 명령**: `/nuri-siege-audit` skill (`.claude/skills/nuri-siege-audit/SKILL.md`, `disable-model-invocation: true` — 수동 invoke) 에 별도 관리. STRATEGY 본문은 canonical verdict 만.
### 3.9 Provisional vs canonical Learning Memory (#468)
`_compute_weights` 가 `recommendations.outcome_30d` 만 read 하던 단일 호라이즌 구조에서, **per-agent 다중 호라이즌 precedence** 구조로 확장. 30d 는 canonical, 21d 는 provisional warm-start. 7d/14d 는 readiness/monitoring only.
**Why 30d is canonical, not changeable**: O'Neil 8주 보유 (CAN SLIM)·Minervini 손익비 3:1 (SEPA) 의 holding window 와 정합. 트레일링 -15% 발동 (PR #202) 도 30d 내 측정. hit/hit_quality 판정 기준 (BUY +5% / SELL -2%) 은 30d 에 한정.
**Why 21d is the only provisional source (no 7-14-21 blend)**: blend 는 horizon-specific decay 가중치를 임의로 설정해야 함 → "heuristic disguised as learning". 21d 는 30d 의 70% 진행률 + sample distribution 비교적 안정. 7d/14d 는 noisy (intraday/short-term 영향) — readiness/monitoring 에만 사용.
**Why per-agent precedence, not global**: agent 별 verdict 빈도가 비대칭. 2026-04-28 production: technical 158 BUY+SELL / risk 5 / retail+crypto 0. global label (single weight source) 은 "일부 canonical, 일부 provisional, 일부 default" 동시 상태를 표현 못 함. per-agent 가 정확한 모델.
**Why `0.10` provisional cap (vs canonical `0.30`)**: weaker evidence (shorter window + same min_agent_records gate) 는 conservative cap. 정확한 calibration 은 별도 작업 (statistical shrinkage, Bayesian posterior). 현 단계는 **policy cap, not inference**.
**Why structural separation, not spy-test**: `compute_canonical_weights` 와 `compute_provisional_weights` 가 별도 함수로 각자 다른 outcome 컬럼만 read. import-graph 가 contract 보장 — Hard veto / amplifier (§2.6) 경로는 `compute_canonical_weights` 만 호출 (provisional 무접근). spy-test (mock + assert_not_called) 는 brittle 하므로 채택 안 함.
**Why retail/crypto 는 `structurally_unsaturating`** (not "underpowered"): 두 agent 는 현 동작 패턴상 BUY+SELL 발동 빈도 0. Natural-wait 으로도 영영 saturate 안 됨. `default_weight` 영구 사용 의도. agent emit 정책 변경은 별도 이슈 (PR scope 밖).
**API surface**: `/api/learning-memory/readiness` per-agent source list 응답 (canonical_30d / provisional_21d / default / structurally_unsaturating + 호라이즌별 sample_count + eligible). 5분 캐시.
**참조**: `nuri/trading/agents/consensus.py` (`compute_canonical_weights` / `compute_provisional_weights` / `select_weight_source` / `agent_readiness`), Migration 23 (`outcome_7/14/21d` 컬럼), `nuri/trading/recommend/tracker.py::TRACK_HORIZONS`.
### 3.10 Strategic Asset Allocation (SAA) — long-term policy mix
**근거 (현대 학술 + 공신력 자료, 2020+)**:
- **Ibbotson & Kaplan** (_FAJ_ 2000, Brinson "93%" 해석 정정): 자산 배분은 **return 분산 (variance over time)** 의 ~90% 를 설명 (return **수준** 이 아님). 종목 선택 / market timing 도 cross-sectional 차이의 30-40% 설명. 자주 오용되는 통계 — "자산 배분이 100% 답" 이라는 단순 결론 X.
- **Vardharaj & Fabozzi** (_J. Portfolio Mgmt_ 2007): modern data 재현 — 자산 배분 도미넌스 확인. Brinson 후속.
- **Andrew Ang** (BlackRock CIO, _Asset Management_ 2014): "Factors are the new asset classes" — momentum / value / quality factor 비중도 자산 배분 차원.
- **Antti Ilmanen** (AQR, _Investing Amid Low Expected Returns_ **2022**): 2020s 저금리·고밸류 환경 → 60/40 expected return 연 4-5% 로 하락. factor diversification + global tilt 권고.
- **Vanguard** _Principles for Investing Success_ 4th ed (**2024**) + Capital Markets Model (**VCMM 2024**): 4 원칙 (goals/balance/costs/discipline). 향후 10년 expected return — US equity 3-5% / Intl 7-9% / US bond 4-5%/yr.
- **Morningstar** _Mind the Gap_ (**2024**) + DALBAR QAIB (**2024**): 투자자 실현 수익 vs 펀드 수익 격차 -1.7%/yr (Morningstar). retail equity vs S&P 500 격차 누적 ~3%/yr (DALBAR, 1994-2023). **discipline (매뉴얼 rebalance) 가 alpha 보다 큰 영향**.
- **Damodaran** (NYU, ERP 2024 update): equity risk premium implied 4.6% (mid-2024) — valuation context.
- **CFA Curriculum** Asset Allocation reading: SAA (장기 정책 mix) 와 TAA (시장 view overlay) 를 **분리된 layer** 로 운영 권고.
- **Bernstein** _Intelligent Asset Allocator_ (2000, 여전히 reference): equal-weight rebalance 가 mean-variance 최적해와 근사 — cov matrix instability 로 강건성 우선.
**핵심 보정 (오용 방지)**:
1. Brinson "93%" = **variance (over time)**, NOT return level. "자산 배분만 잘하면 100% 알파" 는 오독.
2. 2020s 환경 = **low expected return** (Ilmanen 2022). 단순 비중 mix 보다 **비용 최소화 + behavior gap 억제** 가 expected return 의 큰 부분.
3. Factor (momentum/value/quality) 도 asset class — 우리 `quant/factors/` 모듈이 이미 보유 (Ang 2014 framework 정합).
**현재 상태 (2026-05-04 audit)**:
- TAA ✅: `REGIME_ALLOCATION` (`nuri/trading/strategy/longshort.py:23`) — 10 regime × long/short/cash 비중 동적 매핑.
- SAA ❌: 자산 클래스 (주식/채권/원자재/REIT) **장기 target 비중** 미정의. `account_strategies` 는 single-position / sector cap 만, asset class 비중 룰 부재.
**채택 framework** (Vanguard 2024 + Bernstein equal-weight robustness + Ang factor):
- Equal-weight 또는 risk-tolerance 기반 strategic 비중. mean-variance optimization 의 cov matrix instability 회피.
- Account_strategy 별 (core / active / swing / long_term / pension) 다른 SAA target — 위험 허용도 차등 반영.
- Lifecycle glide path (Vanguard target-date 모형): 100 - age = equity % (러프 anchor). 사용자 portfolio.yaml `target_age` 옵션 으로 적용 (Phase 2 후행).
- Factor tilt (Ang 2014): momentum/value/quality 비중은 SAA 위에 overlay (현재 우리 `quant/factors/` 신호 가 반영).
**SAA target 정의** (config/rules.yaml `strategic_allocation_targets` 신설, 사용자 검토 필요):
| account_strategy | us_equity | kr_equity | bond | commodity | cash 최소 | 근거 |
|---|---|---|---|---|---|---|
| `core` | 50% | 20% | 20% | 5% | 5% | Vanguard 3-fund 변형 (KR 추가, US 60% 기준) |
| `active` | 60% | 20% | 10% | 5% | 5% | 적극 — equity 비중 ↑, Ilmanen low-return 환경에서도 risk premium 추구 |
| `swing` | 50% | 30% | 5% | 5% | 10% | 단기 회전 — 현금 buffer ↑ |
| `long_term` | 40% | 20% | 30% | 5% | 5% | 장기 안정 — bond 비중 ↑ |
| `pension` | 30% | 15% | 45% | 5% | 5% | 연금 — Vanguard target-date glide path (60대 기준) |
**Drift threshold**: target 대비 ±5% 이상 deviate → REBALANCE 권고 emit (alpha_action=FLAT 절대 X — STRATEGY §3.7 portfolio_action axis 분리 룰).
**Rebalance cadence** (Morningstar/Vanguard 2024 권고: discipline 우선):
- 정기: 분기 1회 (3/6/9/12 월 첫 영업일).
- 비정기: drift > 10% 또는 regime 전환 시 즉시 권고 (TAA 와 sync).
- **behavior gap 억제**: 시장 timing 시도 X — 기계적 rebalance 가 long-run alpha (DALBAR/Morningstar 2024 데이터).
**TAA × SAA 결합 규칙**:
- SAA = 자산 클래스 비중 (장기 anchor)
- TAA = `REGIME_ALLOCATION` long/short/cash 비중 (단기 overlay)
- 충돌 시: regime-driven cash up 은 TAA 가 SAA 를 **일시** override (방어 우선). regime 정상화 시 SAA 로 회귀.
- factor tilt (Ang 2014): SAA 비중 안에서 factor 신호 (`quant/factors/momentum.py` 등) 가 종목 선택을 가이드.
**미적용 (의도적 deferred)**:
- Mean-variance optimization (`Riskfolio-Lib` 의존성 존재하나 미사용) — Bernstein/Ilmanen 권고대로 cov matrix instability 회피.
- All Weather risk parity (Dalio) — leverage 필요 (4-environment hedge), STRATEGY §7.1 자동 매매 deferred 와 호환 X.
- Yale model (Swensen) — 비전통 자산 (PE / hedge fund) 접근 제약.
**참조**: `config/rules.yaml strategic_allocation_targets` (canonical 값, Phase 1 skeleton), `nuri/analysis/rebalance_advisor.py` (drift 계산 — Phase 2 확장 예정).
### 3.11 소액+측정 모드 (Measurement mode) — 시스템 알파의 입증책임 (#824/#828, 2026-07-07)
**결정**: 시스템 추천을 따르는 실집행 자본을 계좌 equity 비중 **내부**의 "실험 슬리브" sub-cap 으로 한정하고, 나머지 equity 는 §3.10 SAA 기반 broad-index passive core 로 둔다. 슬리브 상한 상향은 아래 사전 고정 판정 기준 통과 + STRATEGY PR 로만 (§2.6 운용 원칙 2 준용). 하향/동결은 상시 허용 (prudential). 입증책임은 시스템에 있다 — 엣지의 기본값은 "없음".
**왜 지금**: 2026-06 Edge Reality Check. Live 성적 (#675, 116 picks / 7wk 단일 강세장): BUY alpha vs SPY +2.8/+5.0/+19.8%p (7/14/30d) 이나 growth-peer QQQ 대비 ~56% beat (30d) — style 효과가 지배하는 표본. 순열 검정은 momentum/RS 엣지 기각 (#709: 퇴화 버그 fix 후 p=0.791), exit 개선 기각 (#715: Δ−0.318, p=0.552 → #800 leader-exit 비활성). 측정 인프라 (#674/#675) 는 가동 중이나 판정 기준이 사전 고정돼 있지 않으면 사후 해석이 반복된다 (§3.6 의 spec amend 거부와 동일 원리).
**Escalation Ladder (§2.6)**: 성적표 원장 = **Surface** (증거 노출만). 슬리브 상한 = 현재 **Surface** (config 선언 — 소비 코드 미배선, 미구축 ⑤) → 배선 후 "슬리브 잔여 소진 시 신규 매수 차단" face 만 **Hard veto** (VIX>30 신규 매수 차단 계열). 상한 **초과 상태의 해소**는 `portfolio_action=REBALANCE` 로만 surface (§3.7/#429 axis — alpha SELL 로 표출 금지). §3.8 축 분리 준수 — 슬리브 상한은 prudential constraint 로만 인용하며, downside-predictive 주장이 아니다. §3.8 이 열어둔 "real-portfolio replay + `recommendations.outcome` 누적" 경로의 실측 개통이 본 절의 측정 대상이다.
**1) 성적표 단일 원장 (ledger of record)**: 판정에 쓰이는 측정 기록 (`decision_outcomes` 등) 의 원장은 **production (Mac mini) DB 단일** (#824) — dev 머신 DB 는 read-replica 이며, 판정·리포트는 원장 쿼리만 인용한다 (2026-07-07 두 원장 혼용 오탐이 계기). 운영 상세 (sync 방향, writer-job 금지) 는 `docs/SOURCE_OF_TRUTH.md` (local), 원장 스냅샷/백업 정책은 미구축 ⑥.
**2) 슬리브 × SAA 결합 규칙** (§3.10 TAA×SAA 패턴 준용): 슬리브는 자산 클래스가 아니라 equity bucket **내부** 구획 (상한 분모 = us_equity+kr_equity **합산** 대비 %) — SAA target/drift ±5% 계산은 슬리브 포함 통상 계산 (이중 계상 없음). 상한 값은 `config/rules.yaml measurement_mode.sleeve_max_equity_pct` (account_strategy 별, canonical). 집행은 §7.1 대로 사용자 수동 — 본 절은 §3.6 Phase 3 (alpha-amplified live) 의 우회 부활이 아니다.
**3) 판정 기준 (2026-07-08 사전 고정 — 사후 amend 거부, §3.6 선례)**:

**사후 추가가 허용되는 유일한 종류 — prudential invalidator** (2026-08-18, #1068 계기로 명문화):
판정을 **보류만 시킬 수 있고 승격은 시킬 수 없는** 조건은 사전등록 이후에도 추가할 수 있다.
사전등록의 목적은 *긍정적 결과의 사후 정당화*를 막는 것인데, 한 방향으로만 작동해 verdict 를
withhold 하기만 하는 조건은 그 남용에 쓰일 수 없기 때문이다 (§2.6 "하향/동결은 상시 허용" 과
같은 논리). 조건 완화·표본 규약 변경·3조건 수정은 여기 해당하지 않으며 종전대로 STRATEGY PR +
재승인 대상이다. **추가 시 의무**: (a) 본 절에 조건과 도입일을 기록, (b) `config/rules.yaml
measurement_mode` 에 임계를 두고 lock test 로 잠가 우발적 완화를 막고, (c) 그 조건이 무효화를
만드는 시나리오를 회귀 테스트로 고정. 첫 사례가 아래 `max_settlement_lag_days` 다.
| 항목 | 값 | 근거 |
|---|---|---|
| 판정일 | 2027-06-30. 조기 승격 금지 (하향은 상시). 표본 emit cutoff = 2027-05-15 (30d 창 완결 보장) | pre-registration — Harvey, Liu & Zhu (2016) multiple testing / p-hacking |
| 표본 규약 | `declared_date` (2026-07-08) ~ emit cutoff 에 emit 된 **US BUY** 결정만 (distinct `decision_id`). 30d window 단일 판정 창 — 7/14d 는 진단용 (30d 는 파일럿 #675 탐색 결과 기반 선택, 판정 표본은 declared_date 이후 disjoint). n ≥ 200. SELL 은 진단 전용 (원장 alpha 는 방향 보정 저장 — tracker 부호 반전) | 원장 실측 σ≈25.0%p (US BUY 30d, n=62, #828 코멘트 쿼리): n=200 의 검출 하한 ≈ +4.4%p/30d (one-sided α=0.05, 80% power), accrual 실측 ~43건/월 → 판정 시점 기대 n≈400 → ≈ +3.1%p. **미검출 ≠ 엣지 부재** (power 한계 명시). §2.1 30-trade 는 per-signal tier, 본 n 은 system-level (별개 축) |
| 벤치마크 | SPY (`forward_outcome_tracker.py` `DEFAULT_BENCHMARK_TICKER` = `measurement_mode.benchmark`). **본 판정은 US-only 로 고정.** #833 착륙 후 KR 결정의 **기록 기준**은 KOSPI (`measurement_mode.benchmark_by_market`, 매 outcome 행의 `benchmark_ticker` 에 자기기술) — 기록 기준이 바뀌었을 뿐 **판정 대상 여부는 그대로**이며, KR 은 **별도 사전등록** 전까지 진단 전용 | #675 caveat: SPY 는 growth 대비 과대평가. KR 을 SPY 로 재면 FX + 시장 스타일이 alpha 에 섞여 부호까지 뒤집힘 |
| 승격 조건 (3개 동시) | mean 30d alpha > 0 · 순열 p < 0.05 (**ticker-block placebo**: 실 표본의 ticker→emit일 구조 유지, 동일 시장 eligible universe 에서 ticker 치환, N=1000, 통계량 = mean 30d alpha, one-sided — 중첩 창·동일일 배치·반복 종목 의존성을 null 이 상속) · **median-decision-date 등분 2분할** 모두 mean alpha > 0 (반기 n 균형 보장) | López de Prado (2018) PBO/deflated-Sharpe 정신 — 단일 통계 아닌 강건성 요구. naive iid 순열은 클러스터링으로 anti-conservative |
| regime 축 | 내부 10-regime 분류는 진단 Surface 전용, 판정 비사용 — 원장 라벨 커버리지 3% (12/383, #828 코멘트 쿼리), 2026-04 이후 transition 1회 (판정 교착 위험), 자기 분류기 순환성 | 실측 2026-07-07 (production 원장) |
| 오염 방지 | `decision_id` 없는 ad-hoc 체결은 표본 제외 (#715 사전등록 원칙의 자본 버전). missing outcome (추적 실패/가격 결측) 은 제외하되 비율을 판정 리포트에 공시 — **15% 초과 시 판정 무효 (측정 연장)** **결측 계상은 창이 *정산*된 것만** — 벤치마크가 만기일 이후 종가를 가진 상태 (#1068, 2026-08-18). 아직 안 온 bar 는 추적 실패도 가격 결측도 아니다; 프로덕션 실측 달력 50.0% vs 정산 9.1%. emit cutoff 가 판정일 46일 전이라 **판정일에는 두 기준이 일치**하므로 사전등록 개정이 아니다 — 바뀌는 것은 측정 중 월간 진행 리포트다. 짝 가드: 정산 프런티어가 `max_settlement_lag_days`(7 — 위 prudential invalidator 정책의 첫 사례, 2026-08-18 도입) 넘게 뒤처지면 `INVALID_STALE_BENCHMARK` 로 판정 차단 (결측률은 정산분만 세므로 수집이 멈추면 오히려 깨끗해 보인다) | Shefrin & Statman (1985) — ad-hoc 개입이 처분효과 재유입 경로. 결측 편향 (탈락은 나쁜 outcome 과 상관 가능) |
**판정 결과 처리**: 3조건 통과 → **US 집행분 슬리브에 한해** 상한 상향 STRATEGY PR (새 상한도 본 표 개정으로 사전 고정). 미달 → 슬리브 유지/축소 + 측정 연장 또는 §3.10 passive 로 수렴 — "조금만 더" 없이 본 표가 답이다. 사전등록 대상은 판정 **기준**이지 상한 초기값이 아니다 — 슬리브 초기값은 판정 표본에 영향이 없으므로 최초 사용자 확정 PR 까지 placeholder 로 두며 일반 PR 로 정정 가능. 확정 이후부터 상향-sticky 발효.
**미구축 (판정 전 선결, follow-up issue)**: ① regime 라벨 백필 — #832 구현 완료 (`scripts/ops/backfill_regime_labels.py` + emit 경로 canonical-or-NULL, 진단용) ② 순열 판정 도구 — #842 구현 완료 (`nuri/quant/validation/decision_alpha.py`, 설계는 본 표에 사전 고정; 기존 `nuri/quant/validation/` 3종은 포트폴리오 Sharpe 전용) ③ 3조건 통합 판정 쿼리 (`/api/alpha` 는 착륙 전 NOT_MEASURABLE 유지) ④ KR benchmark 분리 — #833 구현 완료 (`benchmark_by_market` + `decision_outcomes.benchmark_ticker`, 기록 기준만; KR 판정 사전등록은 미착수) ⑤ 슬리브 상한 소비 배선 (rebalance_advisor / ExecutionFirewall, #834) ⑥ 원장 스냅샷/백업 정책 (#835). 월간 알파 진행 리포트 표출 = #856.
**참조**: `config/rules.yaml measurement_mode` (canonical 값), `nuri/agents/actors/forward_outcome_tracker.py` (측정 파이프라인, 매일 17:00 KST), `docs/SOURCE_OF_TRUTH.md` (원장 매핑, local-only).
### 3.12 held_add 임계 그리드 전방 측정 (#1173 = #788 Stage 1, 2026-08-29 사전등록)
**결정**: held_add 임계(75/75/80)는 바꾸지 않고, "임계가 X 였다면 발화했을까" 를 후보 그리드 전체에 대해 `held_add_would_fire` 원장에 매일 기록한다 (Stage 1). 판정(Stage 2)은 아래 사전 고정 기준으로만 — §3.6/§3.11 과 같은 원리로 **기록이 쌓이기 전에** 고정하며, 사후 amend 는 §3.11 의 prudential invalidator (보류 전용 조건) 만 허용한다.
**왜 지금**: `held_add_shadow` 잡이 6주 연속 0건 emit / 19건 skip — 임계가 과도한지 데이터가 없다. 소급 백테스트(v1)는 survivorship 으로 기각 (#788 Codex 2026-08-21) → v2 = 전방 측정. 그리드·판정 기준은 codex 설계 리뷰 1회전 (NEEDS_REWORK → 반영) 을 거쳤다 (`data/llm_consults/2026-08-29_held-add-would-fire-design-1173.md`).
**canonical 값**: `config/buy_signals.yaml held_add_mode.would_fire_logging` (grid + `stage2_adjudication`) — 잠금 테스트가 드리프트를 차단, 변경은 본 절 개정 PR 로만.
**판정 스펙 (서술 정본)**:
1. **이벤트 행** = (as_of_date, ticker, account). eligible = `earnings_blackout=0 ∧ headroom_pct>0`.
2. **variant 발화** = would_fire_json[V] ≠ null — V 가 어떤 mode 를 고르든 무관 (임계 완화는 current 와 다른 상위 precedence mode 를 고를 수 있고, 그것까지가 측정 대상).
3. **incremental(V)** = V 발화 ∧ current 미발화인 eligible 행.
4. **dedup**: (ticker, account, V) 안에서 7 calendar day 클러스터당 **첫 발화 행** 생존 — 실행했다면 첫 신호에 했을 것 (prospective 규율).
5. **결과 지표**: 30 calendar day 전방 alpha = ticker 수익률 − SPY 수익률. entry = as_of_date 종가, exit = as_of_date+30d 이하 마지막 거래일 종가 (양측 동일 날짜).
6. **추정량**: incremental(V) 의 **표본 중앙값** (paired 아님 — incremental 집합엔 짝이 없다). qualifying = median alpha > 0 ∧ n ≥ 20 ∧ 발화율 제약 충족.
7. **발화율 hard constraint**: 주간 dedup 발화 ≤ 당주 eligible 고유 (ticker, account) 행의 25% — 책 크기에 스케일하고 원장 단독으로 계산 가능 (고정 건수 상한은 오늘의 보유 수를 규칙에 박는다). 초과 variant 는 alpha 무관 탈락.
8. **variant 간 순위**: qualifying 을 median alpha 로 정렬, 상위 2개 차이 ≤ 0.5%p 면 더 보수적(실효 임계 높은) 쪽.
9. **settlement**: 판정은 로깅 시작 + 8주 이후에만, 이벤트는 `as_of_date ≤ 판정일 − 30d` 인 행만 (부분 성숙 꼬리의 기회주의적 포함/제외 차단 — §3.11 emit cutoff 준용).
10. **추론 한계 (명시 사전등록)**: 겹침 창 + 반복 티커로 iid 불성립 — 본 판정은 **기술적(descriptive) 스크리닝**이다. PASS 는 #519 calibration 백테스트 착수 자격만 부여하며, 임계 변경은 여전히 STRATEGY PR + Escalation Ladder.
11. **days_held 공변량 금지**: 소스가 하드코딩 fallback 30 (portfolio 에 entry_date 없음) — 원장에 기록하지 않으며 Stage 2 에서 사용 금지. gates 에 남는 fallback 효과는 전 variant 공유라 variant 간 비교에서 상쇄된다. 소스 수정은 별도 이슈.
**참조**: `nuri/trading/recommend/held_add_would_fire.py` (그리드 계산·기록), `nuri/trading/recommend/held_add.py::evaluate_mode_gates` (측정·라이브 공유 게이트 평가).
## 4. 개발 품질 기준
PR 전 확인.
### 4.1 테스트
| 항목 | 기준 | 현재 |
| Backend tests | Codecov 1% relative regression (목표 ≥ 95%) | 7,962 tests, 368 files (statement coverage **99%** — 17/23,311 미커버 9개 파일, partial branch 81, `make ci-cov` 2026-08-14) |
| Frontend tests | 목표 ≥ 90% | 1606 tests, 141 files |
| E2E | 핵심 flow | 87 Playwright (9 spec) |
| CI | 필수 | lint + test + coverage + security + privacy |
| 네트워크 | 금지 | conftest.py mock |
### 4.2 코드
| 항목 | 기준 |
| Linter | `ruff check` (E/F/W/I) |
| 커밋 | Conventional Commits (영문) |
| PR | 이슈 1 = PR 1, 커밋 ≤ 3 |
| 새 규칙 | `config/rules.yaml`, 하드코딩 금지 |
| 새 임계값 | `config/agents.yaml` |
| 시간 | `kst_now()` / `today_kst()`, `datetime.now()` 금지 |
### 4.3 데이터
| DB 접근 | `nuri/core/db/` 만 |
| 스키마 변경 | `_MIGRATIONS` 리스트, 직접 ALTER 금지 |
| 환율 | DB → OpenBB → `StaleExchangeRateError` (하드코딩 폴백 금지) |
| 외부 데이터 | 최소 10개 외부 소스 교차 |
### 4.4 보안
| 시크릿 | `.env`, git 커밋 금지 |
| 인증 | DASHBOARD_PASSWORD 설정 시 HMAC-SHA256 keyed 토큰 쿠키 (Edge Runtime 호환) |
| CI | Trivy CRITICAL → 머지 차단 |
| LLM | 사용자 portfolio·narrative·의사결정 외부 LLM 전송 금지 (Ollama local only). 공개 RSS 는 §4.4.3 화이트리스트 한정. |
| **개인 금융 데이터** | commit·PR·issue·주석·fixture·CI 로그 절대 노출 금지. `config/portfolio.yaml` gitignored 지만 내용도 추적 대상 금지. broker/수량/평단/잔고/매매이력 모두 해당. |
#### 4.4.1 개인 금융 데이터 enforcement (#138)
**권위 있는 차단 기준**: `scripts/verify/check_privacy_leak.py` 가 ground truth.
| 카테고리 | 차단 대상 | 허용 placeholder |
| Korean broker name | 카카오페이, 미래에셋, 키움증권, 삼성증권, NH투자증권, 토스증권, KB증권, 신한투자증권, 하나증권, 메리츠증권, 유안타증권, 대신증권, 이베스트투자증권, 흥국증권, IBK투자증권 | `Brokerage Alpha/Beta` 등 | <!-- privacy-allow: broker_name — §4.4.1 패턴 표 자체 (#981) -->
<!-- cspell:disable-next-line -->
| Romanized broker | kakaopay, mirae, kiwoom, samsung_securities, nh_invest, toss_securities, shinhan_invest, hana_securities, meritz_securities (case-insensitive substring) | `brokerage_alpha` 등 | <!-- privacy-allow: broker_name — §4.4.1 패턴 표 자체 (#981) -->
| Suspect monetary literal | 7자리 이상 정수 + `total_invested`/`cash_balance`/`deposit`/`withdraw`/`principal`/`net_worth`/`buying_power` 키 | round million (`1_000_000`...`100_000_000`) 자동 허용 |
| **Ticker + PnL 조합** (PR #202) | (a) `[-+]\d+(\.\d+)?%\s*(TICKER)` (`-34% (TEM)`) (b) 인접 `TICKER <signed %>` (`PL +43%`). 소스 + unpushed commit message 스캔. | 규칙 threshold text (`손절 -7%`) ticker 컨텍스트 없으면 통과. `TICKER_FALSE_POSITIVES` frozenset (HWM/SL/MDD/CPI/VIX/BTC/ETH 등 120개). | <!-- privacy-allow: ticker_pnl — §4.4.1 패턴 표 자체 (#981) -->
**의도적 제외**: `한국투자증권` (KIS) 은 Open API 통합 대상 (`nuri/collectors/kis_*`, `docs/KIS_INTEGRATION.md`). 자격 증명은 `config/kis/kis_devlp.yaml` (gitignored by `config/kis/*`, `~/KIS/` legacy 호환).
**Plan / spec 노트 보호 (2026-04-30 Session 8 통합)**: `docs/plans/` 디렉토리 전체가 `.gitignore` 처리됨. 이전에는 개별 파일 (`E3_symmetric_amplifier_design.md`, `507_buy_candidate_emitter_phase1.md`)만 등록됐으나, 새 spec 추가 시 누락 위험 — 디렉토리 단위로 통합. 기존 tracked 3건 (`E3_phase2_paired_counterfactual.md`, `E3_symmetric_amplifier_design.md`, `e4_0b.md`)는 `git rm --cached` 처리. 사용자 본인 spec 노트의 broker name / financial figure 누설 방어. **새 spec 작성 시 broker name placeholder 사용** (`Brokerage Alpha Main` 등) — gitignored 라도 future commit 사고 회피.
**방어 layer 3개** (defense in depth):
1. `scripts/verify/check_privacy_leak.py` — 핵심 scanner (stdlib only).
2. `scripts/verify/pre_push_check.sh` Section 4 — local pre-push gate.
3. `.github/workflows/main-ci-cd.yml` `privacy-scan` — CI gate 모든 PR (frontend-only 예외 없음).
**새 broker 추가**: `scripts/verify/check_privacy_leak.py` `BROKER_NAMES_KO`/`BROKER_NAMES_EN` 튜플 + `tests/scripts/test_check_privacy_leak.py` + 위 표 동시 갱신.
Commit message 스캔 (PR #202 방지):
- pre_push_check.sh Section 4b: `origin/main..HEAD` 의 unpushed commit 을 `--unpushed-commits` 로 스캔 → push 차단
- 로컬 hook 이 정답 — push 후 history 박힘 (Stage 2 필요)
- CLI: `git log -1 --format=%B | python scripts/verify/check_privacy_leak.py --message`
History cleanup (Stage 2 — 별도 작업): main HEAD 는 깨끗하게 유지됨. 이전 commit leak 은 GitHub Support 또는 filter-repo (사용자 명시 승인 필수) 필요. §5.4 스코프 + CLAUDE.md force push 금지 동시 준수 위해 분리.
알려진 미정리 leak (Stage 2 후보):
- PR #202 (squash): commit message body TEM/RKLB/TSLA/PL + PnL. main history 박힘. Stage 2 미실행. §4.4.1 enforcement 는 PR #202 이후 ticker+PnL 사각지대 보완됨 — 신규 leak 은 commit 단계 차단. Tier 3 별도 작업.
#### 4.4.2 외부 데이터 처리 원칙
모든 외부 서비스는 **데이터 클래스별 화이트리스트**.
| 데이터 클래스 | 기본 정책 | 허용 조건 |
| **Tier 0** 공개 (RSS, 공시, 시세, 13F) | 외부 송신 가능 | §4.4.3 등재 provider |
| **Tier 1** 사용자 narrative | 외부 송신 금지 | STRATEGY 개정 + 본인 승인 + retention 정책 |
| **Tier 2** 사용자 portfolio | **절대 외부 송신 금지** | 별도 STRATEGY 개정 + ZDR + 본인 승인. 현재 제한적 Tier 2 (LLM 리포트) 허용 중 (§4.4.3). |
§4.4.1 는 Tier 2 leak 방지, §4.4.3 은 Tier 0 화이트리스트.
#### 4.4.3 외부 LLM Egress Policy (#152, 2026-04-14 개정)
**화이트리스트** 방식. 모든 호출은 `nuri/llm/openai_client.py` 단일 관문.
| Provider | Model | 허용 Tier | 단가 (in/out per 1M) | ZDR | 비고 |
|---|---|---|---|---|---|
| OpenAI | `gpt-5.4-nano` | Tier 0 (RSS 분류) | $0.20 / $1.25 | 권장 | 일 100 헤드라인 연 ~$3.51 |
| OpenAI | `gpt-5.4-nano` | Tier 2 (LLM 일간 리포트) | $0.20 / $1.25 | **필수** | 일 1회, 연 ~$0.10. 2026-04-14 사용자 승인 (프로토타입; local 전환 예정) |
**Tier 2 전제조건**:
1. ZDR 승인 완료 후 첫 호출. 미승인 시 `OPENAI_ZDR_APPROVED=1` 미설정으로 wrapper raise.
2. `NURI_DISABLE_EXTERNAL_LLM=1` 즉시 opt-out.
3. 프롬프트 로그 금지 — token·latency·error_type 만, **content 금지**.
4. ~~local LLM 전환 계획~~ — **dropped (2026-07-08, #854)**: 로컬 LLM 상시 가동 폐지 결정으로 Tier 2 **primary** 는 cloud ZDR 유지. 단 `nuri/llm/report.py` 의 **opt-in local fallback 경로는 제거되지 않았다** — OpenAI 실패 또는 `NURI_DISABLE_EXTERNAL_LLM=1` 시 `LLAMA_MODEL_PATH` → `OLLAMA_HOST` 순으로 시도한다 (둘 다 미설정이면 error note). 즉 "cloud 전용"이 아니라 **"cloud primary + local 상시-미가동 fallback"** 이다. 폐지된 것은 상시 가동과 primary 전환이지 fallback 코드가 아니다.
**필수 운영 룰**:
1. 모든 외부 LLM 은 wrapper (`openai_client.get_client()`). 직접 `import openai` 금지.
2. Per-call audit log — `external_llm_calls` 테이블: `timestamp, provider, model, endpoint, prompt_tokens, completion_tokens, latency_ms, success, error_type`. content 금지.
3. `NURI_DISABLE_EXTERNAL_LLM=1` → `ExternalLLMDisabled` raise.
4. Failure loud — silent fallback 금지. caller 가 graceful degradation 책임.
5. Provider 추가 / 데이터 클래스 확장은 STRATEGY 개정 + 본인 승인.
Deferred (필요 시점에 추가):
- Narrative input UI (Tier 1 정책 결정 후)
- 외부 LLM 비용 모니터링 대시보드 (`external_llm_calls` 테이블 기반)
- ~~Tier 2 → local LLM 전환~~ — dropped (2026-07-08, #854 — on-demand only 결정)
모니터링 트리거: #152 머지 시점 발효. 2026-04-14 Tier 2 추가 후 1주일 동안 비용 예상치 (~$0.02/주) 대비 10× 초과 시 사용자 알림 + `NURI_DISABLE_EXTERNAL_LLM=1` 복귀.
## 5. LLM 에이전트 하네스 (Harness Engineering)
이 프로젝트는 LLM (Claude Code) 이 주요 개발 도구. LLM 은 체계적으로 실패하는 패턴이 있다. 본 섹션은 canonical 원칙 — 실제 사례·진단 절차·Gotcha-Test Pair 프로토콜 상세는 `/nuri-harness-debug` skill (`.claude/skills/nuri-harness-debug/SKILL.md`) 이 on-demand load. Case study 본문은 `git log` (PR #272, #300-#307) 에 보존.
### 5.1–5.6 실패 패턴 (canonical 목록)
6 개 패턴이 시스템적으로 재발한다. 각 패턴의 증상·실제 사례·방어 절차는 `/nuri-harness-debug` skill.
| # | 패턴 | 1-줄 핵심 |
|---|------|----------|
| 5.1 | **할루시네이션** | 존재하지 않는 함수/파라미터/경로를 자신 있게 말함 — 호출 전 시그니처 grep |
| 5.2 | **확증 편향** | 같은 실패를 같은 방식으로 반복 — 2회 실패 시 접근 자체 의심 |
| 5.3 | **유령 수정** | "수정했다" 말하지만 실제 다른 곳 고침 — 수정 후 coverage 로 의도 라인 확인 |
| 5.4 | **스코프 팽창** | 요청 이상 "개선" — 이슈 1 = PR 1, 커밋 ≤ 3 |
| 5.5 | **테스트 환각** | 테스트 통과하지만 타겟 코드 미실행 — coverage 리포트로 라인 실제 커버 확인 |
| 5.6 | **숫자 전파 오류** | 한 곳 변경 후 다른 참조 미업데이트 — `grep -ri "이전값"` 전수 + `make verify-doc-counts` |
#### 5.3.1 Gotcha-Test Pair 원칙 (PR #307)
**모든 fix-pattern gotcha 는 fix 가 사라졌을 때 fail 하는 test 를 명명해서 cite 해야 한다.** 단순 facts/quirks 는 Test: 불필요 (PR body "no fix, just facts" 명시). Folklore 만 남으면 다음 리뷰어가 defensive 코드를 "불필요" 로 제거해도 막을 수 없음 (`df.copy()` 재발 교훈). 프로토콜 상세·enforcement 단계 (1차 리뷰 checklist, 2차 Tier 3 `scripts/audit_phantom_fixes.py` — planned, 미구현) 는 `/nuri-harness-debug` skill.
### 5.7 하네스 구성 요소
| 레이어 | 역할 | 구현 |
|--------|------|------|
| **Context Files** | 프로젝트 규칙 | `CLAUDE.md` 루트 + 13 scoped + `AGENTS.md` + `docs/STRATEGY.md` |
| **MCP Servers** | 외부 도구 연결 | `.mcp.json` → `nuri-read` read-model (stdio · 전 쿼리 `readonly=True` 엔진 강제 · ALLOWED 컬럼만, #1306). raw SQLite 등록은 커밋 기본값에서 제거 — 임의 SQL 이 portfolio/trades 에 닿는다 (§4.4 Tier 2). |
| **Skill Files** | 반복 작업 | `scripts/deploy/deploy_remote.sh`, `scripts/verify/verify.py`, `scripts/db/migrate.py` |
| **Mechanical Enforcement** | 시스템 강제 | ruff · main-ci-cd.yml · pr-discipline.yml · `make verify-*` · SIEGE `gate_check.py` |
**엔트로피 GC**:
| 유형 | 감지 | 방어 |
| Dead code | `ruff` (F401/F841) | CI 차단 |
| Stale data | Freshness SLA | WARN/FAIL 대시보드 |
| Stale tests | Codecov PR comment | 커버리지 하락 경고 |
| Schema drift | `schema_version` + `_MIGRATIONS` | `init_db()` 자동 |
| Config drift | `config/*.yaml` 중앙 | 하드코딩 금지 |
| Number drift | `grep -ri` 전수 | 커밋 메시지 숫자 명시 |
**Context Files 설계**: 거대 단일 파일 ✕ → 디렉토리별 scoped ✓ (루트 + 13개). 코드에서 유추 가능한 정보 ✕ → 결정의 "왜" 만. `STRATEGY.md` 는 작업 전 읽도록 `CLAUDE.md` 에 지시.
### 5.8 하네스 원칙 요약 (2026-04-14 #272 반영, 7개)
1. 모르면 읽는다              — 가정하지 않는다
2. 2번 실패하면 접근을 바꾼다  — 같은 시도 3회 금지. 같은 fix 3회 부분 해결 시 root cause 의심
3. 사용자 워크플로로 검증한다  — mock test ≠ verification. ship 전 `make X --flag` 직접 실행
4. 스코프를 지킨다            — 요청된 것만 한다
5. 숫자를 grep한다            — 한 곳만 고치지 않는다
6. 시스템이 차단한다          — 문서가 아닌 린터/CI/게이트가 강제
7. 외부 API는 측정한다        — 동시성/timeout/rate-limit 추정 금지. yfinance 10-thread OK ≠ KRX 10-thread OK
**변경 이력**: 2026-04-14 — #3 강화 ("실행" → "사용자 워크플로 검증"), #7 추가 (외부 API 측정). Mock-only ship 함정 3회 반복 후 (`#272` 세션, git log).
### 5.9 Case Studies (on-demand reference)
실제 실패 세션의 구체 교훈은 `/nuri-harness-debug` skill 이 canonical. 비슷한 패턴 디버깅 시 auto-trigger 또는 manual `/nuri-harness-debug` invoke.
- **Case #1** — #272 세션 (2026-04-14, 12 PRs): Mock-only 테스트, API 동시성 비대칭, ThreadPool timeout, 사용자 관점 검증, multi-role flow. 본문 → `git log --grep '#272' --since 2026-04-13 --until 2026-04-16`.
- **Case #2** — JKHY 에피소드 (PR #300-#303, #306, #307): dissent overwhelmed, mechanical divergence penalty, 초기 진단 오독 정정. 본문 → `gh pr view 300/301/302/303/306/307`.
### 5.10 Frontier Alignment + Improvement Roadmap (2026-04-30)
§5.8 의 7 원칙은 **2026-02 OpenAI 공표 ("Harness engineering: leveraging Codex in an agent-first world", <https://openai.com/index/harness-engineering/>) + Anthropic Claude Code Best Practices (<https://www.anthropic.com/engineering/claude-code-best-practices>) + 학술 evidence (HAL Kapoor et al. 2026 / AgencyBench Li et al. 2026)** 와 **본질적으로 align**. 다만 frontier 대비 **3 개 measurable gap** 존재. 본 sub-section 은 각 gap 의 정량 spec + acceptance + risk 를 박는다 (TODO 와 분리 — 정책 layer).
#### Gap A. Agent autonomy 확장 (OpenAI 1M LOC pattern)
**Frontier 사례**: OpenAI Codex team — `1,000,000+ LOC` production app, `사람 손 0줄` (2026-02 OpenAI blog). AGENTS.md + mechanical CI invariants + layered architecture (Types → Config → Repo → Service → Runtime → UI) 로 enable.
**현재 상태 (nuri-quant)**: Build/Review/Test/Ship/Reflect 7-phase Flow (§2.7) — 인간 review 단계 mandatory. Codex consult + Claude self-review 양쪽 hooks. Merge 는 사용자 명시 승인. **agent-only PR merge rate ≈ 0%**.
**Gap 의 양면성 (정직한 평가)**:
- *확장 정당화*: harness invariants (privacy-scan, doc count drift, hooks, ruff, conventional commits, ≤3 commits/PR) 가 이미 deterministic 차단 실효. autonomous merge 가 안전한 PR class 존재 (예: doc-only, lint-only).
- *확장 거부 근거*: STRATEGY §7.1 자동 매매 영구 deferred 와 동일 ethos — **financial-impact 코드는 사용자 review 필수**. ₩7M 손실 cascade 직접 경험 후 system 책임 인정한 ecosystem 에서 autonomy 키우는 건 trust budget 역행.
**Acceptance criterion** (research, no commit by default):
- Phase α: PR class taxonomy (doc-only / lint / test / src / config / strategy) 정의 + autonomy_safe_class 명시 (initial: `doc-only` only, ≤ 5% of merged PRs).
- Phase β: `autonomy_safe_class` PR 의 사후 측정 — 4 주 후 regression rate (post-merge revert 또는 fix-forward 빈도) < 10%.
- Phase γ: **strategy / src / config 는 영구 인간 review** (STRATEGY change 필수).
**Priority**: Tier 3 research. 우선순위 낮음. **사용자 review 가 ₩2-4M 손실 회피 가치 (#507 격상 사례) — autonomy 확장 EV 낮음**.
#### Gap B. Harness-model coupling 측정 (AgencyBench-style)
**Frontier evidence**: AgencyBench (Li et al. 2026, 138 real-world tasks, <https://www.preprints.org/manuscript/202604.0428>) — **"agent task reliability 가 model 능력 < harness layer (infrastructure)"** 정량 입증. Same harness × different model = different success rate. HAL (Kapoor et al. 2026, 21,000+ rollouts) 도 동일 결론.
**현재 상태 (2026-08-13 갱신)**: 다중 LLM consumer (`nuri/llm/openai_client.py` gpt-5.4-nano cloud + `scripts/dev/llm_consult.py` codex + local-LLM dual consult). **로컬 모델 축은 측정된다** — `scripts/dev/llm_ab_eval.py` 가 동결 프롬프트 50개로 두 모델을 짝지어 돌리고, `scripts/dev/llm_ab_stats.py` 가 Clopper-Pearson exact CI + McNemar exact 로 판정한다. 첫 적용(2026-08-13)이 `qwen3.5-122b-a10b` → `muse-glimmer-30b` 교체 근거였다 (#1038). **클라우드 축은 여전히 측정 0** — Codex GPT-5.4 → GPT-4-class 강등 시 어느 phase 가 깨지는지 unknown 이고, `openai_client.py` 경로에는 대응 하네스가 없다.
**Acceptance criterion**:
- Phase 1: `data/harness_telemetry.jsonl` 신설 — 매 LLM 호출 기록 (timestamp / model / phase / outcome / token_count). `nuri/llm/openai_client.py` 와 `scripts/dev/llm_consult.py` 양쪽에 wired.
- Phase 2: weekly aggregation script — `make harness-quality-report` → model-별 success rate / failure pattern / phase breakdown. 4 주 데이터 후 model swap recommendation (gpt-5.4-nano vs gpt-5.4 cloud cost-quality tradeoff).
- ✅ Phase 3 (2026-08-13, #1038): nuri-specific eval suite — `config/eval/thesis_prompts.yaml` 동결 프롬프트 **50개**(v1 10 + 적대적 40, 계열 a-j), `thesis_query` 경로 한정. 1차 지표는 `unsafe_price_level`(가격 레벨 날조/유령), 2차는 IFEval 계열 지시준수. LLM judge 를 쓰지 않는다 — 판정자가 흔들리면 A/B 가 무의미하다.
  - **한계 (과잉 인용 금지)**: 프롬프트가 합성·자작이라 외적 타당성이 없고, 투자 판단의 옳고 그름을 재지 않는다(정답 레이블 없음). 프롬프트당 1회만 돌리므로 잡음 바닥이 미측정이다 — `temperature=0.0` 인데도 같은 프롬프트가 런마다 다른 답을 낸 사례가 있다. 다음 스왑 전에 k회 반복을 붙일 것.
**Priority**: Phase 1-2(telemetry) **Tier 2 P2** 로 잔존 — 하네스는 로컬 모델 **교체 판단**만 덮고, 매 LLM 호출의 상시 관측은 아니다.
#### Gap C. HAL evaluation framework 도입 검토
**Frontier evidence**: HAL (Holistic Agent Leaderboard, Kapoor et al. 2026, 21,000+ agent rollouts) — 산업 표준 평가 protocol. SWE-bench (Jimenez et al. ICLR 2024) + AgencyBench 과 함께 frontier benchmark trio.
**현재 상태**: nuri-quant 는 domain-specific (quant 투자) repo. HAL benchmark task (e.g. SWE-bench code editing tasks) 가 직접 적용되지 않음.
**Gap 의 본질**:
- *직접 적용 어려움*: HAL/SWE-bench 는 generic — quant 투자 의사결정 측정 안 함.
- *간접 활용 가능*: HAL methodology (rollout sampling, 표준 evaluation harness) 를 nuri 에 어댑테이션 — `nuri-eval-suite` 신설.
- *비용*: HAL-style evaluation 1 회 ~ \$50-200 (token cost, 1000+ rollouts). 정기 적용 시 cost-quality tradeoff 평가 필수.
**Acceptance criterion** (research):
- Phase 1: HAL methodology 검토 — generic 부분 vs nuri-specific 어댑테이션 가능 부분 분류.
- Phase 2: `nuri-eval-suite` 신설 (예: 50 fixed test cases on portfolio analysis / signal scoring / earnings preview) — Gap B 의 telemetry 와 통합.
- Phase 3: Quarterly evaluation report → model swap / harness change 의사결정 입력.
**Priority**: **Tier 3 research**. Gap B 가 선행 (Gap C 는 Gap B 의 데이터 위에 build). 단독 build 는 EV 낮음.
#### Frontier alignment 종합
| Frontier 권장 | nuri-quant 적용 | Gap |
| AGENTS.md + machine-readable instructions | ✅ `AGENTS.md` + `CLAUDE.md` + `STRATEGY.md` | 0 |
| Mechanical CI invariants | ✅ privacy-scan, doc count drift, ruff, hook | 0 |
| Layered architecture | ✅ `nuri/core/` → `collectors/` → `quant/` → `trading/` → `api/` | 0 |
| Pre-commit deterministic hooks | ✅ `.claude/settings.json` PreToolUse/PostToolUse | 0 |
| Conventional commits + scope discipline | ✅ ≤3 commits/PR, 1 issue = 1 PR | 0 |
| Subagents (parallel, context isolation) | ✅ codex consult + local-LLM dual | 0 |
| Skills (reusable templates) | ✅ `make` targets + `nuri-*` skills | 0 |
| **Agent autonomy (OpenAI 1M LOC)** | ⚠ 인간 review 필수 (의도된 conservative) | **Gap A** |
| **Harness-model coupling 측정** | ❌ telemetry 없음 | **Gap B** (Tier 2 P2) |
| **Standardized eval framework (HAL)** | ❌ 없음 | **Gap C** (Tier 3 research) |
**결론**: 7 of 10 frontier 권장 적용. 3 gap 은 측정 + 결정 layer (autonomy / coupling / eval) — **시스템 코드가 아니라 시스템에 대한 시스템**. Tier 2 P2 (Gap B) 만 **build value 즉시**, 나머지는 research / 정책 결정.
### 5.11 BUY Signal Asymmetry — #507 Phase 1 ship + Phase 2 v2 sequence (2026-04-30 Session 8)
**문제 (4-29 발견, #507 격상)**: 시스템이 `Collect → Analyze → Consensus → Certify → Track` 전체에서 **sell-side gate 7개** 와 **buy-side emitter 0개** 를 운영. SIEGE / stop-loss / take-profit / position-limit / VIX / holdings_monitor 모두 SELL 또는 block. 4월 사용자 ₩3.25M 실현 + ~₩2-4M 추정 기회비용 attribution. 자세한 inventory: `data/llm_consults/2026-04-30_507-system-audit.md`.
**Phase 1 ship (PR #508 / #512)**:
- `nuri/trading/recommend/buy_candidate_emitter.py` — factor + momentum + RSI + breakout fusion → BUY candidate stream + entry/stop/TP1/TP2.
- `_get_held_tickers()` SELL/TRIM/REDUCE filter + `_get_cooldown_tickers(days=5)` 단일 cooldown (PR #508 ship 시).
- API + read-side dual-layer guard (PR #512): `recommendations.action ∈ {SELL,TRIM,REDUCE}` 는 portfolio JOIN으로 0주 ticker 차단.
- `FRESHNESS_POLICIES["portfolio"]` 24h warn / 72h fail 정책 등록.
- 4-30 brief 검증: GOOGL/TSM 0주 SELL 누설 0건, MSFT/GOOGL 신규 매수 후 brief surface 정상.
- **잔여 결손**: held=skip 100% / threshold 70 floor / cooldown 5d uniform / brief에 freshness 미surface / 신규 매수 시 consensus 수동 호출 / 0주 HOLD stale row.
**Phase 2 spec v2 sequence (Session 8 codex+Qwen consult REJECT v1)**:
1. **#517 (2b)** — Cooldown SELL-type split + event taxonomy 통일. Forward-only ALTER (no backfill). `payload.action_type ∈ {hard_sell, trim_action, position_reduce, divergence_alert}`. hard_sell 21d / trim 0d (re-add allowed) / reduce 7d / divergence 3d / legacy fallback 5d. Session-level dedup lock for trim 0d spam.
2. **#518 (2a)** — Held add-mode + multi-account cap + earnings blackout. 3 modes precedence (`tp1_residual_add` > `ride_winner` > `average_down`) — 같은 (ticker, account, session) 단 1건 emit. Account별 cap: `account_strategies.<acct>.cap_max` derive (active=25%, core=15%, hardcoded 금지). Avg_down window: `account.stop_loss × [0.3, 0.7]` derive. **Earnings blackout: held_add는 earnings_date ± 5d 차단** (binary event risk). **Shadow mode 14d 의무** — 첫 14일 brief 미surface, calibration sample 생성.
3. **#519 (2c)** — Threshold backtest 104 weekly (2024-04 ~ 2026-04). In-sample 60% / OOS 40% (peek 금지). Objective: max profit_factor s.t. MaxDD ≥ -10% AND n_emit ≥ 1.5/session. Liquidity-tier slippage. Tie-break: T*와 1σ within 시 conservative 선택. **3-LLM consult 의무**.
**v1 → v2 변경 (LLM 8개 STOP/REFINE 합의)**:
- 시퀀스: ~~2b → 2c → 2a~~ → **2b → 2a (shadow) → 2c** (threshold tune은 held-add 활성 후 calibrate)
- C1 sample: ~~13 weekly Q1-2026~~ → **104 weekly 2년**
- A3 hardcoded [-3,-10] → account-derived
- A4 cap hardcoded 5%p → account_strategy derive
- A2 mutual exclusion: 3 modes 같은 ticker 동시 emit 차단
- B2 backfill 폐기 (heuristic 위험)
- E2 multi-account cap 분리
- G 정량 수치 ~₩1.2-2.3M 폐기 → April audit replay에서 backtest로 derive
**Spec**: `docs/plans/507_buy_candidate_emitter_phase2_spec.md` (gitignored, v2 작성 완료)
**Consult archive**: `data/llm_consults/2026-04-30_507-phase2-spec-review.md`
### 5.12 Session 8 결함 격상 (2026-04-30, #513–#516)
Phase 1 ship + brief 재실행 검증 중 발견된 4건 — 별도 PR로 fix:
| # | 발견 | 우선순위 |
| **#513** | `premarket_brief.py`가 `FRESHNESS_POLICIES["portfolio"]` 결과를 brief 본문에 surface 안 함 (backend 작동, 사용자 가시성 0) | P1 |
| **#514** | `recommendations.action='HOLD'` 행이 portfolio JOIN filter 미적용 → 0주 ticker (TSM 등) HOLD noise surface | P2 |
| **#515** | 신규 매수 후 `make consensus` 수동 호출 운영 burden — `scripts/ops/import_portfolio.py` 에 newly-added ticker detection + auto-trigger 필요 | P1 |
| **#516** | Pension 계좌 4월 매도 3종목 재진입 — 증권사 자동매수 설정 의도 검증 필요 | P3 |
### 5.13 BUY candidate backtracking ledger (Session 8 신설)
**Goal**: Phase 1 emitter score 신뢰도 검증 + Phase 2c threshold backtest 표본 자동 적립.
**Mechanism**:
- 매 세션 emit한 BUY 후보를 `data/reports/buy_tracking/candidate_ledger.jsonl` (gitignored, append-only)에 baseline 기록.
- 다음 세션 진입 시 `scripts/analysis/compare_buy_candidates.py --session N` (tracked infra) 실행 → baseline vs current close + tier별 평균 return.
- 4주간 누적 → 13 weekly samples → Phase 2c threshold backtest 입력 보강.
**Tier 정의**:
- `A_high`: 고확신 (AI capex 직결, fundamentals 강함)
- `B_mid`: 중확신 (catalyst 후 진입)
- `C_chase`: 추격 회피 (5d momentum 과열, breakout+RVOL 후만)
- `ADD_ride`: 보유 ride-winner (Phase 2a 미ship 수동 판단)
- `ADD_held`: 보유 add (Phase 2a 미ship 수동 판단)
**검증 항목 (acceptance — score function 신뢰도 측정)**:
- A_high 평균 1d return > 0 → score 신호 valid
- A_high − C_chase spread > 0 → score 차등화 valid (5d momentum 과열이 더 잘 가는 비정상 차단)
- ADD_ride peak 대비 흐름 → ride-winner 명분 정량 검증
- B_mid 평균 → catalyst 전이 측정
**Session 8 baseline**: 11종 (A_high 3 / B_mid 3 / C_chase 2 / ADD_ride 1 / ADD_held 2). 4-29 close 기준. 다음 세션 첫 task로 검증 실행 (`NEXT_SESSION.md` cold-start 체크리스트).
**부정 결과 시 액션**: A_high avg < 0 → 즉시 P0 격상 + Phase 2c threshold backtest 우선순위 격상 + score function 재교정 issue 격상.
### 5.14 Conversational / Reasoning Failure Patterns (observational, 2026-05-27 신설)
§5.1-5.6 = **코드/툴 레벨** mechanical failure patterns. §5.14 = **대화/추론 레벨** behavioral patterns (사용자와의 응답 흐름에서 발생). 별도 numbering 이유: 다른 class, 다른 방어 메커니즘 (gate 강제 어려움, 1차 = 인간 규율 + memory cross-session 보존).
| 패턴 | 증상 | 방어 |
|---|---|---|
| **5.14.1 Data→Recommendation Slide** | 데이터 수집/분석 결과 공유 요청에 대해 silent 하게 종목/액션 권고로 변환 (user 명시 요청 없이 자의적 advice) | user 가 명시적 권고 요청 ("X 어떻게 생각해", "deploy 어디에", "추천해") 했는지 확인 후만 권고. data presentation 은 ranking / 사실 / freshness 까지만. 권고 시작 전 1 step pause: "user 가 결정 권고 요청했는가? 아니면 정보만 요청했는가?" |
| **5.14.2 Cross-context Inconsistency** | 같은 정량 filter / rule 을 시장 / 도메인 별로 다르게 적용 (예: KR universe blow-off 보류 → US universe blow-off 진입 권고) | Filter 기준 (60d return cap, vol threshold, blow-off 제외) 을 **명시 선언** 후 모든 시장에 동일 적용. 권고 전 self-check: "내가 컨텍스트 A 에서 적용한 rule 을 B 에 동일 적용하면 통과?" |
**Case studies**: `.claude/skills/nuri-harness-debug/SKILL.md` Part B (canonical narrative — session 2026-05-27 정정 사례 + git log reference). 본 절은 pattern definition 만 보유.
**Enforcement layer**: 1차 = user-level memory (cross-session reinforcement). 2차 = `/nuri-harness-debug` skill 진단. 3차 (미구현) = hook 으로 mechanical 강제 어려움 (LLM 응답 layer, structured 검출 metric 없음).
**Gotcha-Test Pair**: N/A — behavioral pattern, 코드 fix 아님. `*(facts, no fix)*` 마킹.
## 6. SIEGE Gate 명세 (v2)
모든 추천은 아래 조건군을 통과해야 CERTIFIED. 1 개라도 **error** 실패 시 REJECTED. Warning 은 누적만.
**v2 (PR #312, #248)**: 조건 개수 **가변**. `certify()` 가 asset class (us_equity / kr_equity / kr_index / commodity / bond) 별 5/7/8 조건을 per-class expansion 후 flatten. 고정 "11-gate" 명칭 deprecated.
### Base 조건 (asset class 공통)
| # | 조건 | 등급 | 기준 |
|---|------|------|------|
| 1 | position_limit | error | `account_strategies.<s>.per_position_max` — core 15%, active 25%, swing 30%, long_term 25%, pension 40% |
| 2 | sector_limit | error | `position_limits.max_sector_exposure` = 35% (전략 공통) |
| 3 | stop_loss | error | `account_strategies.<s>.stop_loss` — core -7, active -10, swing -15, long_term -20, pension -30. `pnl_pct < account_sl` 위반 시 error. (`stock_types.yaml` growth/value 는 `stop_loss.per_stock/value` 에만 존재, SIEGE 미참조.) |
| 6 | leverage_ban | error | `leverage.banned_etfs` (TSLL/TQQQ/SQQQ/UPRO/SPXU, `nuri/core/rules.py::LEVERAGE_ETFS`) 미보유 |
| 9 | conflict_free | warning | BUY/SELL 충돌 없음 |
| 10 | drift_safe | warning | 매수 후보 critical drift 없음 |
| 11 | macro_event_alignment | warning | \|event_score\| ≥ 10 경고 |
### Per-asset-class 조건 (v2 expansion)
`siege_gates.asset_classes.<class>` 정의. primary + secondary flatten.
| # | 조건 | 등급 | 출처 |
| 5 | data_fresh | warning | `freshness_primary` + `freshness_secondary[]` + `freshness_max_hours` |
| 7 | volatility_gate | warning | `volatility_primary` + threshold (+ secondary). us_equity VIX>30, kr_equity USD/KRW 3d>3% + VIX>30, kr_index KOSPI 3d>5% + USD/KRW>3% |
| 8 | external_data | warning | `external_min_records` + `external_min_sources`. us≥10/3, kr≥5/2. **kr_index/commodity/bond = `external_applicable:false` → N/A vacuous pass** (애널리스트 컨센서스/13F 가 구조적으로 비적용인 자산군이라 영구 미충족 warning 대신 N/A 처리; kr_equity 는 적용 유지 — 커버리지 존재하나 KR external collector 미구현이라 warning 이 정직) |
**예시**: us_equity 3 + kr_equity 2 포트폴리오 flatten 결과 (2026-04-16 기준) = base 8 + data_fresh 3 + volatility 3 + external_data 2 = **총 16 conditions**. 다른 포트폴리오는 다른 수치. 상세 per-class rule: `config/rules.yaml siege_gates` + `docs/CERTIFICATION_SPEC.md`. 생성 로직: `nuri/trading/engine/certification.py` `_check_{freshness,volatility,external}_for_class()` → `certify()` flatten.
## 7. 작업 정책
운영 backlog (Tier 1/2/3) 는 `docs/TODO.md`. STRATEGY 는 **변하지 않는 정책** 만. 새 세션 시작 시 `NEXT_SESSION.md` → `docs/TODO.md`.
### 7.1 자동 매매 — 영구 deferred (사용자 opt-out)
| 항목 | 이슈 | 결정 사유 |
|------|------|---------|
| Alpaca 실전 (Paper → Live) | [#17](https://github.com/researcherhojin/nuri-quant/issues/17) | **영구 보류**. 2026-04-11 사용자 결정 — 자동 매매 손실 책임소재. 시스템 추천(확률적)과 실제 매매(결정적) 경계 모호화 차단. |
| KIS Open API 매매 endpoint | — | **영구 보류** (동일 사유). `kis_realtime.py` **read** endpoint (잔고/가격/drift) 는 유지. |
**원칙**: 시스템은 추천·알림만. 실제 주문은 사용자가 증권사 앱에서 수동. `DryRun` / paper trading 은 백테스트/검증용으로 유지. 뒤집으려면 STRATEGY 개정 PR + 재승인.
### 7.2 작업 규칙 (PR discipline)
- 이슈 1개 = PR 1개, 커밋 ≤ 3
- 새 발견 → 별도 이슈, 같은 PR 묶지 않음
- Tier 건너뛰지 않음 (Tier 2 시작 전 Tier 1 close)
- `docs/TODO.md` 함께 업데이트, 이슈 번호 필수
## 8. 오픈소스 레퍼런스
### 투자 이론
| 출처 | 적용 | 위치 |
| O'Neil, *CAN SLIM* | 손절 -7%, 익절 +20%/+40%, 8주 보유 | `config/rules.yaml` |
| Minervini, *SEPA* | 트레일링 -15%, 3:1 손익비 | `config/rules.yaml` |
| Shefrin & Statman 1985 | 처분효과 경고 | 익절 규칙 근거 |
### 아키텍처/엔진
| [SIEGE Engine](https://github.com/nutshells3/Swarm-Intelligence-Engine-with-Gated-Execution) | Gate-based certification, event journal (외부 v1, 본 프로젝트 v2 asset-class expansion) | `nuri/trading/engine/` |
| [Palantir Foundry](https://www.palantir.com/docs/foundry/data-lineage/overview) | Data Health, Decision Intelligence (#178) | `nuri/core/freshness.py`, `events.py`, `decisions` |
| [Dagster](https://docs.dagster.io/guides/observe/asset-freshness-policies) | Freshness SLA | `nuri/core/freshness.py` |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | 멀티에이전트 합의 | `nuri/trading/agents/` |
| [Riskfolio-Lib](https://riskfolio-lib.readthedocs.io/) | Risk Parity | `nuri/analysis/rebalance.py` |
| [López de Prado](https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086) | Walk-forward · 순열 검정 null-safe gate (#701/#702) | `nuri/quant/validation/strategy_walkforward.py` |
### UX
| 출처 | 참고 |
| [Ghostfolio](https://github.com/ghostfolio/ghostfolio) | 미니멀 대시보드, progressive disclosure |
| [React Flow](https://reactflow.dev/) | 파이프라인 DAG |
| [FreqUI](https://www.freqtrade.io/en/stable/freq-ui/) | 백테스트 시그널 마커 |
