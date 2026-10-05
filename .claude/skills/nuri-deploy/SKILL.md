---
name: nuri-deploy
description: Deploy to Mac Mini production server. Use when asked to "deploy", "배포", "push to production", or "서버 반영".
---

# Deploy Workflow

## Pre-deploy checks

```bash
make pre-deploy        # Safety checks (config + DB + gate + frontend build + API + ports)
make verify-all        # Full verification (tests + backend + frontend, no network)
```

Both must pass before deploying. If either fails, fix the issue first.

## Deploy

```bash
make deploy-mini       # MBP → Mac mini 7-step sync (git pull ff-only + config scp + frontend rebuild + scheduler reload)
```

`deploy_to_mini.sh` reloads the scheduler (unload → load), restarts the resident
API and discord-bot via `kickstart -k` (`RESIDENT_SERVICES`, #940), and bounces the dashboard only when
`build_frontend.sh` rebuilds it. Manual equivalent for the API:
`launchctl kickstart -k gui/$(id -u)/com.nuri-quant.api`. Editing a **plist**
needs a full reinstall (`launchctl unload` → copy → `load`); `kickstart` re-execs
the cached job definition and will not pick up an edited file.

## Post-deploy verification

Run these **on the Mac mini** — the API binds `127.0.0.1` and is not reachable
over the LAN by design.

1. SSH to Mac Mini and verify the service is running
2. Check scheduler heartbeat: `cat data/.scheduler_heartbeat`
3. Verify API responds: `curl http://127.0.0.1:8001/api/pipeline/status`
4. Verify the proxy path (catches a stale `next build`, whose baked
   `routes-manifest.json` 404s every `/api/*`):
   `curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/api/pipeline/status`
5. Check dashboard loads: `http://<mini-ip>:3000` (login required —
   `DASHBOARD_PASSWORD` in `frontend/.env.local`)

## Rollback

If something breaks after deploy:

```bash
# On Mac Mini
make backup            # Ensure current DB is backed up first
git log --oneline -5   # Find the last good commit
git checkout <sha>     # Revert to last good state
```
