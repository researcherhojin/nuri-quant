# Operations Runbook

Operator-facing details for running Nuri-Quant in production. The OSS visitor entry point is `README.md`; this file is the **maintainer / operator runbook** — 2-machine setup, deploy procedure, scheduler reload, recovery paths.

## 2-Machine Topology (canonical)

Nuri-Quant runs across two Apple Silicon Macs. The MBP is the dev workstation; the Mac mini is the 24/7 production receiver.

|  | M5 Max MacBook Pro (dev) | M2 Pro Mac mini (24/7 receiver) |
|---|---|---|
| Hostname | `Ehbebeui-MacBookPro.local` | `Ehbebeui-Macmini.local` |
| Role | Development, analysis, manual runs, PR work | Production scheduler, data collection, Discord alerts |
| Code sync | `git push` → | launchd `com.nuri-quant.autopull` every 5 min (git fetch + `--ff-only` merge + change analysis) |
| Config sync | `make deploy-mini` → | `.env`, `portfolio.yaml`, `NEXT_SESSION.md` via SCP (DB **excluded** — Mac mini DB is production) |
| Scheduler | N/A | apscheduler `nuri/scheduler.py` running under launchd, ~24 jobs (collectors / consensus / backtest / weekly 1y universe backfill) |
| State sync (dev↔dev) | `make sync-start` (pull) / `make sync-end` (push) | passive (sshd) |

`DEV2_HOST` env var lives **only in `~/.zshrc`** (NOT `.env`) — `sync_dev.sh` copies `.env` between machines, so an `.env`-resident `DEV2_HOST` would make each machine point at itself.

## Standard Deploy: `make deploy-mini`

Run from MBP after a PR merges to `main`. `scripts/deploy_to_mini.sh` performs 6 steps automatically (~30 seconds total):

1. **SSH connection check** — fail-fast if `$DEV2_HOST` unreachable
2. **Remote `git pull --ff-only`** — picks up the merged PR
3. **Config sync** — `.env` + `portfolio.yaml` + `NEXT_SESSION.md` (DB excluded — Mac mini DB stays canonical)
4. **`uv sync`** — only when `uv.lock` / `pyproject.toml` changed
5. **Scheduler reload** — only when `nuri/scheduler.py` / `config/agents.yaml` / `config/rules.yaml` changed (auto-installs launchd plist on first run)
6. **Verification** — git HEAD parity + scheduler PID alive + autopull state

Prerequisites:
- `export DEV2_HOST=user@macmini.local` in `~/.zshrc` (not `.env`)
- SSH key registered MBP → Mac mini (ed25519 in current setup)

## Sub-commands

| Command | Purpose | When to use |
|---------|---------|-------------|
| `make deploy-mini` | Full 6-step sync | Default after every merged PR |
| `make scheduler-reload-remote` | Mac mini scheduler reload only | After `nuri/scheduler.py` change without PR (rare) |
| `make sync-start` | Dev↔dev pull (other machine → this machine) | Switching active machine; `--with-reports` / `--no-claude` flags supported |
| `make sync-end` | Dev↔dev push (this machine → other) — DB included, prompts confirm | Ending a session before switching machines |
| `make sync-status` | Read-only HEAD + `NEXT_SESSION` timestamp comparison | Sanity-check both machines aligned |
| `make backup` | DB backup (30-day rolling) | Pre-risky-deploy or scheduled |
| `make pre-deploy` | Safety checks before legacy `make deploy` | Pre-rsync flow only |
| `scripts/sync_dev.sh push\|pull` | Low-level wrapper | Manual / debug |
| `bash scripts/autopull_receiver.sh` | Mac mini receiver (`fetch + ff-only + change-analysis`) | Driven by launchd `com.nuri-quant.autopull` every 5 min — do not invoke manually unless debugging the receiver |

## Mac mini autopull (launchd)

`com.nuri-quant.autopull` (`~/Library/LaunchAgents/com.nuri-quant.autopull.plist`):
- **StartInterval** 300 (every 5 min)
- **ProgramArguments** `/bin/bash scripts/autopull_receiver.sh`
- **Logs** `data/logs/autopull.log` / `autopull.err`

The plist installs automatically on first `make deploy-mini` if missing. Status check: `launchctl list | grep nuri-quant`.

## Scheduler control

Scheduler runs under separate launchd `com.nuri-quant.scheduler.plist`. It is **NOT installed by `make deploy-mini`** — first install requires manual `launchctl bootstrap` (one-time on Mac mini setup).

- View jobs: `python -m nuri.scheduler --list-jobs` (24 jobs across collectors / consensus / backtest)
- Reload after config change: `make scheduler-reload-remote` (or 5th step of `deploy-mini` auto)
- Kill: `launchctl unload ~/Library/LaunchAgents/com.nuri-quant.scheduler.plist`

## Recovery

| Symptom | Action |
|---------|--------|
| Mac mini behind on git HEAD | `make sync-status` → if behind, `make deploy-mini` from MBP. If autopull is broken, `tail data/logs/autopull.err`. |
| Scheduler died | `launchctl list \| grep scheduler` — if absent, re-bootstrap. If present but PID 0, `launchctl unload` then `bootstrap`. |
| Mac mini DB drifted from MBP | **Don't auto-sync** — Mac mini DB is canonical for production. If MBP needs Mac mini DB, `make sync-start` (pull). Reverse direction (MBP → Mac mini DB) requires explicit confirmation prompt in `make sync-end`. |
| KIS token expired (Mac mini) | Token cache lives in `config/kis/` (gitignored). Re-auth: `python -m nuri.collectors.kis_realtime` once on Mac mini. |
| Discord alert silent | Check Mac mini scheduler log for `discord` job error. Webhook URL lives in `.env` — re-sync via `make deploy-mini` if rotated on MBP. |
| launchd plist corrupted (autopull / scheduler) | `launchctl list \| grep nuri-quant` shows missing or PID 0. `launchctl bootout gui/<uid>/<label>` then re-bootstrap from the canonical plist in repo (`scripts/launchd/`). Re-run `make deploy-mini` to auto-install autopull plist. |
| SSH key revoked / fingerprint mismatch | `ssh -v $DEV2_HOST` to inspect handshake. Re-add MBP key to Mac mini `~/.ssh/authorized_keys`. `make deploy-mini` SSH check (Step 1) fail-fast surfaces this immediately — no partial deploy. |
| Disk full on Mac mini | `df -h` over SSH. Likely culprits: `data/logs/*.err` (rotate or `logrotate.d` setup if unset), `data/reports/<date>/` accumulation (rolling 30-day cleanup script), `data/db_backup/` (30-day rolling — verify cron). DB itself ~MB-scale, rarely the cause. |

## Configuration files (gitignored, sync via deploy-mini)

| File | Purpose | Notes |
|------|---------|-------|
| `.env` | API keys (FRED, OpenAI ZDR, Discord webhook), Alpaca creds (paper only — auto trading deferred), runtime flags | DEV2_HOST does NOT belong here |
| `config/portfolio.yaml` | User holdings (account labels, qty, avg price) | Real values — privacy scanner blocks pattern leaks in commits |
| `config/kis/kis_devlp.yaml` | KIS Open API credentials | Token cache also lives in `config/kis/` |
| `NEXT_SESSION.md` | Session handoff — last session's checklist + next work item | Auto-loaded session start; supersedes stale memory |

DB (`data/portfolio.db`) is intentionally NOT synced — Mac mini DB is the canonical production state. Backup only.

## Local LLM stack (M5 Max ↔ Mac mini)

Dual-stack pattern, single helper: `scripts/llm_consult.py` (codex + Qwen3.5 archive). Both backends expose the OpenAI-compatible `/v1/chat/completions` shape; the helper picks via `NURI_LLM_QWEN_URL` / `NURI_LLM_QWEN_MODEL` env vars (`.env.example` has both forms commented).

| Machine | Backend | Port | Model | When to use |
|---------|---------|------|-------|-------------|
| **M5 Max MBP** (dev) | LM Studio (MLX) | 1234 | `qwen3.5-122b-a10b` (4-bit MLX) | Interactive `make llm-consult` during sessions. MLX = ~63 tok/s on M5 Max, GUI lifecycle, multi-model concurrency. |
| **M2 Pro Mac mini** (24/7 receiver) | llama.cpp (GGUF) | 8081 | `qwen3.5-122b-a10b-q4` (Q4_K_M GGUF) | Headless production. Smaller footprint than Electron-based LM Studio. Currently not load-bearing — install only when a Mac mini consumer (e.g. scheduler-side classifier) actually needs local LLM. |

**Why dual-stack rather than one**: MLX 4-bit quantization preserves accuracy better than GGUF Q4_K_M on Apple Silicon and is faster (~50% throughput at the same model size). LM Studio's GUI is convenient on the dev box. Mac mini, conversely, runs headlessly under launchd — `brew install llama.cpp` + GGUF + a `keepalive` plist is more hermetic than an Electron app and survives reboots without the desktop session.

**No code changes needed to swap** — `scripts/llm_consult.py` reads `NURI_LLM_QWEN_URL` / `NURI_LLM_QWEN_MODEL` from env. Defaults are the LM Studio dev shape; Mac mini sets the llama.cpp shape in its `.env` only when local LLM consumers are actually deployed there.

**Current state (2026-04-29)**: only the dev box runs LM Studio. Mac mini has no local LLM running because no Mac mini code path calls one — `nuri/llm/openai_client.py` is the only LLM gateway and it talks to OpenAI cloud (gpt-5.4-nano). Set up Mac mini llama.cpp **only when** a code path on the receiver needs local inference (e.g. if `macro_news` classifier ever migrates from OpenAI cloud to local for cost / privacy).

## BUY Candidate Backtracking (2026-04-30 Session 8 신설)

**Goal**: Phase 1 BUY emitter score 신뢰도 검증 + Phase 2c threshold backtest 표본 누적. 자세한 정책: `docs/STRATEGY.md §5.13`.

### 매 세션 사이클

1. **세션 N 종료 시**: emit한 BUY 후보 11종 (또는 그 세션 N개)을 `data/reports/buy_tracking/candidate_ledger.jsonl` (gitignored, append-only)에 baseline 가격 + tier (`A_high` / `B_mid` / `C_chase` / `ADD_ride` / `ADD_held`) + score + stop/TP1/TP2 사전 계산 박힘.
2. **세션 N+1 진입 시 (의무, SESSION_PROMPT.md SESSION-START #2)**:
   ```bash
   .venv/bin/python scripts/compare_buy_candidates.py --session N
   # 또는 특정 close 기준:
   .venv/bin/python scripts/compare_buy_candidates.py --session N --as-of 2026-05-01
   ```
3. 출력: ticker별 ret%, vs TP1, vs Stop, ✅ TP1 hit / ❌ STOP hit / 📈 진행 중 verdict, **tier별 평균 return**.
4. 4가지 검증 항목 (`docs/STRATEGY.md §5.13`) 정량 평가 후 `data/reports/buy_tracking/<date>_session<N>_buy_candidates.md` backtrack 표 채우기.
5. 부정 결과 (A_high avg < 0) → P0 격상 + Phase 2c 우선순위 격상 + score function 재교정 issue.

### 4 주 누적 후

13 weekly samples 자동 적립 → Phase 2c (#519) threshold backtest 입력 보강. 2024-04 ~ 2026-04 historical 데이터와 함께 104 weekly window 구성.

### 파일 위치

- Ledger: `data/reports/buy_tracking/candidate_ledger.jsonl` (gitignored, JSON line per emit)
- 사람용 표: `data/reports/buy_tracking/<date>_session<N>_buy_candidates.md` (gitignored, baseline + backtrack 표 2개)
- 비교 스크립트: `scripts/compare_buy_candidates.py` (**tracked**, 재사용 인프라, ~75 LOC)

## Portfolio sync (broker app → DB)

매 세션 시작 의무 (SESSION_PROMPT.md SESSION-START #6):

1. broker 앱 화면 캡처 (모든 활성 계좌 — Brokerage Alpha Main / Sub / Brokerage Beta / Pension / IRP).
2. `config/portfolio.yaml` (gitignored) 의 holdings + cash 갱신.
   - 신규 매수 ticker 추가 시 broker name placeholder 사용 (`Brokerage Alpha Main` 등 — STRATEGY §4.4.1).
   - cash_krw / cash_usd 분해 정확도 확인 (총합 = 화면 표시 현금).
3. `python scripts/import_portfolio.py` 실행 — yaml → DB sync (4 accounts, holdings 키 정의된 계좌만 대상).
4. `make consensus` 실행 — 신규 ticker가 stale recommendation (4-30 이전 SELL conf 100 등) 으로 brief에 잘못 표시되지 않도록 4-30 date row 갱신.
   - 자동화는 #515 (`scripts/import_portfolio.py` 에 newly-added ticker detection + auto-trigger) 추가 예정.
5. `make brief` (또는 `make quick-scan`) 실행 — 새 holdings + cash 반영된 brief 검증.

## Reference

- Deploy script: `scripts/deploy_to_mini.sh`
- Sync script: `scripts/sync_dev.sh` (push / pull modes)
- Receiver script: `scripts/autopull_receiver.sh`
- Portfolio sync: `scripts/import_portfolio.py`
- BUY candidate backtracking: `scripts/compare_buy_candidates.py`
- launchd plists: `~/Library/LaunchAgents/com.nuri-quant.{autopull,scheduler}.plist`
- Architecture (DB schema, env var inventory, CI/CD): `docs/ARCHITECTURE.md`
- Investment policy / harness rules: `docs/STRATEGY.md`
- File-ownership map (which file owns which fact): `docs/SOURCE_OF_TRUTH.md`
