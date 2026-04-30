---
name: nuri-deploy
description: Deploy to Mac Mini production server. Use when asked to "deploy", "배포", "push to production", or "서버 반영".
---

# Deploy Workflow

## Pre-deploy checks

```bash
make pre-deploy        # Safety checks (lint + test + gate)
make verify-all        # Full verification with network
```

Both must pass before deploying. If either fails, fix the issue first.

## Deploy

```bash
make deploy            # rsync to Mac Mini (M2 Pro, 24/7 production)
```

## Post-deploy verification

1. SSH to Mac Mini and verify the service is running
2. Check scheduler heartbeat: `cat data/.scheduler_heartbeat`
3. Verify API responds: `curl http://<mini-ip>:8001/api/pipeline/status`
4. Check dashboard loads: `http://<mini-ip>:3000`

## Rollback

If something breaks after deploy:
```bash
# On Mac Mini
make backup            # Ensure current DB is backed up first
git log --oneline -5   # Find the last good commit
git checkout <sha>     # Revert to last good state
```
