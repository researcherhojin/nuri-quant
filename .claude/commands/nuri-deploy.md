---
description: MBP → Mac mini (M2 Pro, 24/7 production) deploy via `make deploy-mini` (rsync + 6-step sync). gstack `/land-and-deploy` 와 다름 — 외부 PaaS (Fly/Render/Vercel) 아닌 self-hosted SSH+rsync 환경 전용. Usage `/nuri-deploy`.
---

`nuri-deploy` 스킬을 invoke 하라. `.claude/skills/nuri-deploy/SKILL.md` 의 4-phase 절차를 따라:

1. Pre-deploy: `make pre-deploy` + `make verify-all` (둘 다 통과 필수)
2. Deploy: `make deploy` (MBP → Mac mini rsync)
3. Post-deploy verification: scheduler heartbeat / API :8001 / Dashboard :3000
4. Rollback (필요 시만): `make backup` + `git checkout <last-good-sha>`

주의: 자동 매매 deploy 아님. 추천/알림 시스템 배포만 (STRATEGY §7.1 Auto trading deferred).
