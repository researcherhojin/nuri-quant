# scripts/ — Operational + dev tooling index

nuri-quant 의 모든 shell + Python script 모음. 카테고리별 sub-directory 구조 (PR-A #557 modularization, PR-B #X rename + index).

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
├── episodes/            # historical experiments (e3_*/e4_*/pr_f_*)
├── launchd/             # macOS plist + cron install/uninstall
└── hooks/               # git hooks (pre-commit)
```

## verify/ — pre-commit + CI checks

| Script | Purpose | Use |
|---|---|---|
| `verify_all.sh` | full verification (lint+test+gate) | `make verify-all` |
| `verify.py` | full functional verification (analysis run + `data/reports/` save) | `make verify-fast` (`--skip-backtest`) / `make verify` (full) |
| `verify_doc_counts.sh` | doc count drift check (CI-enforced) | `make verify-doc-counts` |
| `check_drift.py` | universe / strategy drift detect | `.venv/bin/python scripts/verify/check_drift.py` (pre-push gate Section 1) |
| `check_atomic.sh` | commit atomicity (1 logical change/commit) | `bash scripts/verify/check_atomic.sh` |
| `check_privacy_leak.py` | block personal financial data leak | pre-push hook + CI privacy-scan |
| `check_universe_coverage.py` | universe.yaml coverage validate | `.venv/bin/python scripts/verify/check_universe_coverage.py` |
| `pre_push_check.sh` | pre-push gate (privacy + lint + test) | git pre-push hook |
| `gate_check.py` | pre-stage gate validation (Makefile 단계 실행 전 호출) | `make validate` / `make regime` / `make recommend` 내부 |

## deploy/ — deploy + sync between machines

| Script | Purpose | Use |
|---|---|---|
| `deploy_remote.sh` | generic SSH push (rsync) | `make deploy` |
| `deploy_to_mini.sh` | MBP → Mac mini 1-command (7 steps) | `make deploy-mini` |
| `autopull_receiver.sh` | Mac mini receiver (5min cron, NOT push) | launchd `com.nuri-quant.autopull` |
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

## ops/ — operational + health

| Script | Purpose | Use |
|---|---|---|
| `health_check.sh` | schema version + table existence | hourly launchd cron |
| `import_portfolio.py` | YAML → DB portfolio import | `make setup` 내부 (`$(PYTHON) scripts/ops/import_portfolio.py`) |
| `notify_scan_result.py` | Discord scan result publish | `make full-scan` 마지막 단계 |
| `ports.sh` | check + kill running services | `bash scripts/ops/ports.sh [kill]` |
| `run_phase2_chain.py` | #529 Phase 2 4-actor chain end-to-end | `make phase2-chain ticker=X` |
| `discord_embed_smoke.py` | Discord embed format smoke test | dev only |
| `gen_cspell_tickers.py` | `.cspell/tickers.txt` 생성 (universe.yaml 기반) | `make cspell-tickers` |
| `gen_kr_names.py` | `config/kr_ticker_names.json` KR 종목명 캐시 생성 | `make kr-names` |
| `reconcile_toss.py` | Toss 보유 → portfolio diff (dry-run) | `make reconcile-toss` |

## analysis/ — one-off analysis

| Script | Purpose |
|---|---|
| `compare_buy_candidates.py` | candidate diff between snapshots |
| `siege_history.py` | SIEGE certification history report |
| `siege_predictivity_audit.py` | E4-0b predictivity audit |
| `stage1_classifier_plausibility.py` | Stage 1 classifier plausibility check |

## dev/ — developer tooling

| Script | Purpose | Use |
|---|---|---|
| `setup.sh` | venv + deps + DB init | `make setup` |
| `start.sh` | API + Dashboard start | `make start` |
| `demo.sh` | demo workflow run | `bash scripts/dev/demo.sh` |
| `ci_local.sh` | local CI parity (~30s smoke / full) | `bash scripts/dev/ci_local.sh [--lint\|--quick]` |
| `codex_review.sh` | Codex CLI review wrapper | `bash scripts/dev/codex_review.sh` |
| `install_hooks.sh` | git hooks install | `make setup-hooks` |
| `llm_consult.py` | codex + Qwen3.5 dual-archive consult | `make llm-consult slug=X prompt=path` |
| `agent_loop.py` | agent loop orchestrator skeleton (#577/#578, file-based transcript) | dev only |

## doc/ — documentation maintenance

| Script | Purpose | Use |
|---|---|---|
| `sync_doc_counts.sh` | sync doc counts (tests/files/tables/etc) | `make sync-doc-counts` |
| `validate_portfolio.py` | portfolio config validation | `make validate-portfolio` |
| `validate_universe.py` | universe.yaml validation | `make validate-universe` |

## episodes/ — historical experiments (archived)

PR/이슈 단위로 한 번 실행한 backfill / counterfactual / amplifier replay scripts. 새 작업은 여기 추가하지 말 것. 이력만 보존.

| Script | Origin |
|---|---|
| `e3_3_backfill.py` | E3 Phase 3 backfill |
| `e3_3b_stage2_counterfactual.py` | E3 Stage 2 counterfactual analysis |
| `e3_amplifier_paired_replay.py` | E3 amplifier paired replay |
| `e3_amplifier_stage0_audit.py` | E3 amplifier Stage 0 precondition |
| `e4_0a_api_smoke.py` | E4 Phase 0a API smoke test |
| `pr_f_atr_validation.py` | PR F ATR rule validation |

## launchd/ — macOS launch agents (cron)

| Plist | Schedule | Action |
|---|---|---|
| `com.nuri-quant.autopull.plist` | 5min | Mac mini autopull receiver |
| `com.nuri-quant.scheduler.plist` | continuous | apscheduler daemon |
| `com.nuri-quant.api.plist` | continuous (KeepAlive) | FastAPI :8001 (#838) |
| `com.nuri-quant.dashboard.plist` | continuous (KeepAlive) | Next.js dashboard :3000 (#838) |
| `com.nuri-quant.discord-bot.plist` | continuous | Discord bot daemon |
| `com.nuri-quant.health-check.plist` | hourly | health_check.sh |
| `com.nuri-quant.heartbeat-watchdog.plist` | 15min | scheduler heartbeat watchdog + 자동 재시작 (#778/#779) |
| `com.nuri-quant.state-replicator.plist` | daily | state_replicator.sh |
| `com.nuri-quant.sre-scan.plist` | hourly | SREIncidentAgent.scan |

Install: `bash scripts/launchd/install_crons.sh [--only X] [--exclude Y] [--dry]`
Uninstall: `bash scripts/launchd/uninstall_crons.sh [--only X]`

## hooks/ — git hooks

| Hook | Action |
|---|---|
| `pre-commit` | advisory lint auto-fix (ruff `--fix`, 비차단) — privacy scan 은 pre-push (`pre_push_check.sh` Section 4) 소관 |

Install via `bash scripts/dev/install_hooks.sh`.

## 추가 가이드

- `_common.sh` 는 root 유지 (모든 sub-dir 의 .sh 가 `source ../_common.sh` 로 참조)
- 신규 script 추가 시: 카테고리 결정 → 해당 sub-dir 에 추가 → 본 README table 갱신
- 일회성 실험은 `episodes/` (다른 PR 후 reuse 안 할 것)
- 파일명 컨벤션: snake_case, verb_noun (예: `migrate.py`, `verify_all.sh`)
- shell scripts: 첫 줄 `#!/usr/bin/env bash`, `set -euo pipefail`
