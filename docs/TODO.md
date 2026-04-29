# Nuri-Quant — Work Backlog

이 문서는 **앞으로 할 일**만 기록한다. 완료된 항목은 git log + closed PR + closed issue 가 진실 source. 새 작업을 시작하기 전에 이 순서를 확인하고, 새 발견은 GitHub 이슈로 등록한 뒤 이 표에 추가한다.

정책 (자동 매매 영구 deferred, 작업 규칙) 은 `docs/STRATEGY.md §7` 에 있다. 이 문서는 operational backlog 만 담는다.

---

## Tier 2 — 다음 1 달 (P1)

**다음 세션 우선순위** — 구체적 작업 단위로 엄밀 정의 (2026-04-14 재평가).

| 우선 | # | 항목 | 이슈 | 카테고리 | 예상 | Acceptance |
|------|---|------|------|---------|------|------------|
| ~~🔴 P0~~ | ~~0~~ | ~~**E3 Symmetric Amplifier — Phase 2 paired counterfactual**~~ | — | ~~feat(engine)~~ | ~~1-2 세션~~ | **Permanently shelved 2026-04-29 (3-LLM consensus: Codex+Qwen3.5+Claude)** — Phase 1 shadow (#479) + Phase 2 paired counterfactual (PR #496, 30d FAIL / 60d/90d PASS) shipped. Phase 3 (alpha-amplified live) **각하**. 결정적 근거: STRATEGY §7.1 auto-trade 영구 deferral → E3 effect path = conf-boost-only on recommendations → 사용자 manual judgment 가 이미 자연 moderation → Phase 3 product value chain broken. Redesign options (a/b/c/d) 모두 각하 (sample/universe/threshold 변경은 power-limit 미해결 또는 result-fitting risk; macro_events 누적 후 재시도는 §7.1 deferral 이 product 답을 안 바꿈). 60d/90d PASS 는 STRATEGY §3.6 에 "supportive horizon evidence" 로 기록. Reopen trigger: §7.1 reversal 시 fresh spec 재작성 후 Phase 2 재실행. Phase 1 shadow telemetry 영구 유지 (`enabled: false` 무기한). 자세한 Round 1/2 verdicts: `data/llm_consults/2026-04-29_e3-phase2-{shelve-decision,round2-three-way}.md` (gitignored, 사용자 머신 local). |
| ~~🟡 P1~~ | ~~1~~ | ~~**#272 Phase 5 (QA): Negative + Smoke run**~~ | — | ~~test~~ | ~~1 세션 (네트워크 필요)~~ | **Closed 2026-04-29** — Phase 5 negative 3건 (`TestPhase5NegativeGuardrails` missing/malformed/empty universe.yaml graceful error) + 5 coverage checks (`validate-universe`) + 2 fetch checks (S&P 500 / KOSPI 200) all PASS. baseline (2026-04-15) 대비 회귀 0 (prices/fundamentals/analyst/insider/superinvestor 99/99/97/97/97% 유지). Mac mini scheduler 24/7 running smoke 정상. Fresh-clone 은 의도적으로 skip — Mac mini 가 동일 환경에서 매일 cron 으로 동일 path 검증 (running smoke = fresh-clone equivalent). `docs/SMOKE_RUN.md` 에 2026-04-29 re-smoke execution log 섹션 append. 다음 monitoring: 분기별 또는 dependency 변동 시. |
| ~~🟡 P1~~ | ~~2~~ | ~~**기술분석 통합 to 추천 파이프라인**~~ | — | ~~feat(recommend)~~ | ~~1-2 세션~~ | **Shipped 2026-04-29 (PR #497)** — Framing 정정 후 ship: entry-stage defense (PR #303 divergence penalty + risk_agent veto) 이미 있음. 진짜 gap 은 hold-stage falling-knife. `nuri/trading/recommend/holdings_monitor.py` 신규 — 2 trigger (TechnicalAgent SELL ≥ 80, divergence with tech ≥ 70), 7d dedup via `pipeline_events`, REVIEW CTA only (STRATEGY §7.1 auto-trade deferred). 20 lock-tests, 07:10 KST APScheduler. Live dry-run 검증: 1/15 holdings alerted. |
| ~~🟡 P1~~ | ~~3~~ | ~~**Universe weekly 1y backfill 자동화**~~ | — | ~~ops~~ | ~~0.5 세션~~ | **Shipped earlier** — `nuri/scheduler.py` SCHEDULES 에 `stock_us_backfill` (Sun 05:00 KST, `period=1y, source=all`) + `stock_kr_backfill` (Sun 05:30 KST, `days=365, source=all`) 등록 완료. `create_scheduler` 에 `kwargs=job.get("kwargs", {})` 적용. universe-only ticker stale gap closed. |
| ~~🟡 P1~~ | ~~4~~ | ~~**Earnings quality 분석 통합**~~ | — | ~~feat(recommend)~~ | ~~0.5 세션~~ | **Tier 3 research 로 이관** (2026-04-15). Codex challenge 로 (a) JKHY 실측 surprise 가 4-17% 정상 beat (HARNESS.md §2 에 기록된 "0.0~0.2% soft beat" 는 unit 오독에서 온 문서 오류), (b) literature (Bartov 2002, Kasznik & McNichols 2002, Neururer 2020) 는 meet/beat streak 을 **양의** 신호로 본다. 원안 spec 은 repo-wide unit inconsistency + mature large-cap false positive + literature 반대 방향 문제로 **기각**. 재설계는 Tier 3 "research note" 참조. |
| 🟢 P2 | 5 | **포트폴리오 온보딩 UI (YAML → Dashboard)** | [#25](https://github.com/researcherhojin/nuri-quant/issues/25) | feat(frontend) | 2-3 세션 | 수동 yaml 편집 제거. 2026-04-14 portfolio.yaml 수동 수정 페인포인트 직접 경험 |
| 🟢 P2 | 6 | **OpenBB 호환성 fix** | [#274](https://github.com/researcherhojin/nuri-quant/issues/274) | bug(collectors) | 1 세션 | openbb-core==1.6.7 ↔ openbb-news==1.6.1 충돌로 news/etf_flows 수집 불가. 점진적 upgrade 필요 (콜렉터별 smoke test 후 진행) |
| 🟢 P2 | 7 | **#272 Phase 2c-3 — universe-check 필수 게이트화** | — | ops | 10분 | `make collect-universe` 5/5 PASS 상태 유지 중 → 사용자 수동으로 branch protection required check 토글 |
| ⚪ P3 | 9 | **flaky test 일반 stabilization** | — | test | 1 세션 | #295는 resolved. 다른 flaky 후보 (parallel sys.modules 오염 패턴) 전수 감사 |
| ~~🟢 P2~~ | ~~10~~ | ~~**Scheduler 로그 노이즈 감축 (잔여)**~~ | — | ~~chore(scheduler)~~ | ~~0.5 세션~~ | **Fully shipped 2026-04-29**. (c) RotatingFileHandler PR #498 (5MB × 3 backup, env var tunable). (a/b) PR #501 — global yfinance logger WARNING in `_configure_logging` + `events.ETF_TICKERS` frozenset (~50 entries) short-circuit before yfinance call. 4 lock-tests (1 logger silencing + 3 ETF skip). 새 log surface: `🪙 N ETF skip` separate from `❌ N failed`. |

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
