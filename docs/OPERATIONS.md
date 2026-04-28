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

Run from MBP after a PR merges to `main`. `scripts/deploy_mini.sh` performs 6 steps automatically (~30 seconds total):

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
| `bash scripts/auto_deploy.sh` | Mac mini receiver (`fetch + ff-only + change-analysis`) | Driven by launchd `com.nuri-quant.autopull` every 5 min — do not invoke manually unless debugging the receiver |

## Mac mini autopull (launchd)

`com.nuri-quant.autopull` (`~/Library/LaunchAgents/com.nuri-quant.autopull.plist`):
- **StartInterval** 300 (every 5 min)
- **ProgramArguments** `/bin/bash scripts/auto_deploy.sh`
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

## Reference

- Deploy script: `scripts/deploy_mini.sh`
- Sync script: `scripts/sync_dev.sh` (push / pull modes)
- Receiver script: `scripts/auto_deploy.sh`
- launchd plists: `~/Library/LaunchAgents/com.nuri-quant.{autopull,scheduler}.plist`
- Architecture (DB schema, env var inventory, CI/CD): `docs/ARCHITECTURE.md`
- Investment policy / harness rules: `docs/STRATEGY.md`
- File-ownership map (which file owns which fact): `docs/SOURCE_OF_TRUTH.md`
