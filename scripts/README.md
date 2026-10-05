# scripts/ — Operational + dev tooling index

nuri-quant 의 shell · Python 스크립트 색인. 스크립트는 카테고리별 하위 디렉터리에 둔다 (#557).

## 구조

```
scripts/
├── _common.sh           # shared bash helper (sourced by other .sh)
├── README.md            # this file
│
├── verify/              # check + lint + drift verification
├── deploy/              # deploy + sync + autopull receiver
├── db/                  # DB migration + maintenance + backup
├── ops/                 # operational + health + import + run
├── analysis/            # one-off analysis (siege, comparison)
├── dev/                 # dev tooling (setup, ci_local, codex review)
├── doc/                 # doc count sync + portfolio/universe validation
├── ci/                  # CI helpers (test duration merge)
├── episodes/            # historical experiments (e3_*/e4_*/pr_f_*)
├── launchd/             # macOS plist + LaunchAgent/LaunchDaemon install
├── hooks/               # git hooks (pre-commit, pre-push)
└── _archive/            # retired scripts, not maintained
```

## verify/ — pre-commit + CI checks

| Script | Purpose | Use |
|---|---|---|
| `verify_all.sh` | full verification (lint+test+gate) | `make verify-all` |
| `verify.py` | full functional verification (analysis run + `data/reports/` save) | `make verify-fast` (`--skip-backtest`) / `make verify` (full) |
| `verify_doc_counts.sh` | doc count drift check (CI-enforced) | `make verify-doc-counts` |
| `check_drift.py` | universe / strategy drift detect | `.venv/bin/python scripts/verify/check_drift.py` (pre-push gate Section 1) |
| `check_atomic.sh` | commit atomicity (1 logical change/commit) | `bash scripts/verify/check_atomic.sh` |
| `check_privacy_leak.py` | block personal financial data + personal-identifier shapes | pre-push hook + PreToolUse hook + CI `Privacy Leak Scan` |
| `check_universe_coverage.py` | universe.yaml coverage validate | `.venv/bin/python scripts/verify/check_universe_coverage.py` |
| `check_lock_major_bump.py` | `uv.lock` major-version boundary check | CI `uv.lock Major Boundary` + `dependabot-auto-merge.yml` |
| `check_orphan_imports.py` | first-party import 가 실제 모듈을 가리키는지 검사 | `verify_all.sh` 내부 |
| `check_pyright_diff.py` | push 가 추가·변경한 줄의 pyright 오류만 검사 | `pre_push_check.sh` Section 2e |
| `pre_push_check.sh` | pre-push gate (drift + lint + shellcheck + doc counts + spellcheck + pyright + test + privacy) | git pre-push hook (`--skip-tests`) / 수동 전체 실행 |
| `gate_check.py` | pre-stage gate validation (Makefile 단계 실행 전 호출) | `make validate` / `make regime` / `make recommend` 내부 |

## deploy/ — deploy + sync between machines

| Script | Purpose | Use |
|---|---|---|
| `deploy_remote.sh` | generic SSH push (rsync) | `make deploy` |
| `deploy_to_mini.sh` | MBP → Mac mini 1-command (7 steps) | `make deploy-mini` |
| `ssh_dev2.sh` | 원격 ssh helper (IPv4 강제 + `.local` 해석 실패 시 fallback) | `deploy_to_mini.sh` · Makefile 내부 |
| `verify_head_sync.sh` | 로컬 · 원격 git HEAD 일치 판정 | `deploy_to_mini.sh` 내부 |
| `autopull_receiver.sh` | Mac mini receiver (5min cron, NOT push) | launchd `com.nuri-quant.autopull` |
| `build_frontend.sh` | frontend rebuild when code is newer than `.next` — backup/rollback + dashboard bounce; shared by autopull and deploy_to_mini (#1462) | `bash scripts/deploy/build_frontend.sh` |
| `pre_deploy_check.sh` | safety check before deploy | `make pre-deploy` |
| `sync_dev.sh` | low-level rsync state (push/pull) | `bash scripts/deploy/sync_dev.sh push` |
| `dev_sync.sh` | session start/end wrapper (uses sync_dev.sh) | `make sync-{start,end,status}` |
| `state_replicator.sh` | DR replica state sync | `bash scripts/deploy/state_replicator.sh {primary,replica,verify}` |

## db/ — DB migration + maintenance

| Script | Purpose | Use |
|---|---|---|
| `migrate.py` | schema migration runner | `make setup` 내부 (`$(PYTHON) scripts/db/migrate.py`) |
| `maintenance.py` | VACUUM + ANALYZE periodic | apscheduler daily |
| `backup.sh` | SQLite backup → `data/backups/` | `make backup` |
| `restore.sh` | restore from backup | `bash scripts/db/restore.sh <snapshot>` |
| `pull_backup.sh` | 서버 최신 백업 1벌을 개발 머신으로 복사 + sha256 대조 | `bash scripts/db/pull_backup.sh` |

## ops/ — operational + health

| Script | Purpose | Use |
|---|---|---|
| `health_check.sh` | schema version + table existence | Discord `/health` on-demand (cron 미설치 — #939) |
| `import_portfolio.py` | YAML → DB portfolio import | `make setup` 내부 (`$(PYTHON) scripts/ops/import_portfolio.py`) |
| `notify_scan_result.py` | Discord scan result publish | `make full-scan` 마지막 단계 |
| `ports.sh` | check + kill running services | `bash scripts/ops/ports.sh [kill]` |
| `run_phase2_chain.py` | #529 Phase 2 4-actor chain end-to-end | `make phase2-chain ticker=X` |
| `discord_embed_smoke.py` | Discord embed format smoke test | dev only |
| `gen_cspell_tickers.py` | `.cspell/tickers.txt` 생성 (universe.yaml 기반) | `make cspell-tickers` |
| `gen_kr_names.py` | `config/kr_ticker_names.json` KR 종목명 캐시 생성 | `make kr-names` |
| `reconcile_toss.py` | 브로커 보유 내역 → portfolio diff (dry-run) | `make reconcile-toss` |
| `reap_orphan_runs.py` | 완료 보고 없이 남은 `agent_run_ledger` 행 정리 (기본 dry-run) | `python scripts/ops/reap_orphan_runs.py [--apply]` |
| `backfill_regime_labels.py` | `recommendations.regime` 진단용 라벨 백필 | `python scripts/ops/backfill_regime_labels.py [--dry-run]` |
| `backfill_decision_regime.py` | `decisions.regime` 백필 (`agent_verdicts` 에서 복사) | `python scripts/ops/backfill_decision_regime.py [--dry-run]` |
| `machine_alive.sh` | 머신 생존 신호 (스케줄러 heartbeat 와 별개) | launchd `system/com.nuri-quant.machine-alive.plist` |

## analysis/ — one-off analysis

| Script | Purpose |
|---|---|
| `compare_buy_candidates.py` | candidate diff between snapshots |
| `placeholder_vote_impact.py` | 자리표시자 verdict 를 가중 투표에서 뺐을 때의 판정 변화 (읽기 전용) |
| `siege_history.py` | SIEGE certification history report |
| `siege_predictivity_audit.py` | E4-0b predictivity audit |
| `stage1_classifier_plausibility.py` | Stage 1 classifier plausibility check |

## dev/ — developer tooling

| Script | Purpose | Use |
|---|---|---|
| `setup.sh` | venv + deps + DB init | `make setup` |
| `start.sh` | API + Dashboard start | `make start` |
| `demo.sh` | demo workflow run | `bash scripts/dev/demo.sh` |
| `ci_local.sh` | local CI parity (6.4s smoke / full) | `bash scripts/dev/ci_local.sh [--lint\|--quick]` |
| `codex_review.sh` | Codex CLI review wrapper | `bash scripts/dev/codex_review.sh` |
| `install_hooks.sh` | git hooks install | `make setup-hooks` |
| `seed_e2e_db.py` | e2e 용 합성 seed DB 생성 | CI `Frontend E2E` (`--db` 필수) |
| `llm_consult.py` | codex + local-LLM dual-archive consult | `make llm-consult slug=X prompt=path` |
| `agent_loop.py` | agent loop orchestrator skeleton (#577/#578, file-based transcript) | dev only |
| `llm_ab_eval.py` | 로컬 모델 A/B — 동결 프롬프트 50개, 결정론적 채점 (LLM judge 없음) | `python scripts/dev/llm_ab_eval.py --model-a X --model-b Y` |
| `llm_ab_stats.py` | A/B 판정 — Clopper-Pearson exact CI + McNemar exact (stdlib only) | `llm_ab_eval.py` 가 import |
| `llm_ab_rescore.py` | 저장된 출력 재채점 (모델 호출 없음) — 채점기 수정의 영향 확인용 | `python scripts/dev/llm_ab_rescore.py --show-failures` |

## doc/ — documentation maintenance

| Script | Purpose | Use |
|---|---|---|
| `sync_doc_counts.sh` | sync doc counts (tests/files/tables/etc) | `make sync-doc-counts` |
| `validate_portfolio.py` | portfolio config validation | `make validate-portfolio` |
| `validate_universe.py` | universe.yaml validation | `make validate-universe` |
| `round_test_durations.py` | `.test_durations` 소수 자릿수를 4자리로 고정 | `make sync-test-durations` 내부 |

## ci/ — CI helpers

| Script | Purpose | Use |
|---|---|---|
| `merge_test_durations.py` | CI shard 별 duration 파일 병합 | `make sync-test-durations-from-ci` |

## episodes/ — historical experiments (archived)

PR · 이슈 단위로 한 번 실행한 backfill / counterfactual / amplifier replay 스크립트. 이력 보존용이며 새 작업은 추가하지 않는다.

| Script | Origin |
|---|---|
| `e3_3_backfill.py` | E3 Phase 3 backfill |
| `e3_3b_stage2_counterfactual.py` | E3 Stage 2 counterfactual analysis |
| `e3_amplifier_paired_replay.py` | E3 amplifier paired replay |
| `e3_amplifier_stage0_audit.py` | E3 amplifier Stage 0 precondition |
| `e4_0a_api_smoke.py` | E4 Phase 0a API smoke test |
| `pr_f_atr_validation.py` | PR F ATR rule validation |

## launchd/ — macOS launch agents (cron)

`launchd/*.plist` 는 사용자 도메인 LaunchAgent, `launchd/system/*.plist` 는 시스템 도메인 LaunchDaemon 이다.

| Plist | Schedule | Action |
|---|---|---|
| `com.nuri-quant.autopull.plist` | 5min | Mac mini autopull receiver |
| `com.nuri-quant.scheduler.plist` | continuous | apscheduler daemon |
| `com.nuri-quant.api.plist` | continuous (KeepAlive) | FastAPI :8001 (#838) |
| `com.nuri-quant.dashboard.plist` | continuous (KeepAlive) | Next.js dashboard :3000 (#838) |
| `com.nuri-quant.discord-bot.plist` | continuous | Discord bot daemon |
| `com.nuri-quant.health-check.plist` | hourly | health_check.sh — prod 미설치 (#939: 고유 검사는 SRE detector 로 이식) |
| `com.nuri-quant.heartbeat-watchdog.plist` | 15min | scheduler heartbeat watchdog + 자동 재시작 (#778/#779) |
| `com.nuri-quant.state-replicator.plist` | hourly | state_replicator.sh — 7일 넘은 `snapshot_*.db` 정리 포함 (#1576) |
| `com.nuri-quant.sre-scan.plist` | hourly | SREIncidentAgent.scan |
| `system/com.nuri-quant.machine-alive.plist` | 10min | machine_alive.sh (부팅 직후 로드, 로그인 무관 — #1443) |

Install (LaunchAgent): `bash scripts/launchd/install_crons.sh [--only X] [--exclude Y] [--dry]`

Install (LaunchDaemon): `sudo bash scripts/launchd/install_daemons.sh`

Uninstall: `bash scripts/launchd/uninstall_crons.sh [--only X]`

## hooks/ — git hooks

| Hook | Action |
|---|---|
| `pre-commit` | 스테이지된 `.py` 에 `ruff check --fix` + `ruff format`, `frontend/` 의 JS/TS 에 `eslint --fix` 후 재스테이징. 비차단 |
| `pre-push` | `scripts/verify/pre_push_check.sh --skip-tests` 실행. 실패 시 push 차단 |

Install: `make setup-hooks` (`scripts/dev/install_hooks.sh`, 심볼릭 링크).

## 추가 가이드

- `_common.sh` 는 root 유지 (모든 sub-dir 의 .sh 가 `source ../_common.sh` 로 참조)
- 신규 script 추가 시: 카테고리 결정 → 해당 sub-dir 에 추가 → 본 README table 갱신
- 일회성 실험은 `episodes/` (다른 PR 후 reuse 안 할 것)
- 파일명 컨벤션: snake_case, verb_noun (예: `migrate.py`, `verify_all.sh`)
- shell scripts: 첫 줄 `#!/usr/bin/env bash`, `set -euo pipefail`
