# Mechanical Enforcement

Hook config: `.claude/settings.json`. CI workflows: `.github/workflows/main-ci-cd.yml`. Pre-push: `scripts/hooks/pre-push` (installed by `make setup-hooks`) → `scripts/verify/pre_push_check.sh --skip-tests` (6.6s, 2026-08-21 M5 Max — #1132 가 pytest collect ~2.5s 를 더함; 테스트는 CI shard 매트릭스가 미러하고 full 로컬 실행은 320.8s 라 훅에서는 뺀다 — 느린 훅은 우회당한 훅이다). 이 문장은 #1070 까지 **거짓**이었다: 게이트 스크립트는 있었지만 `scripts/hooks/` 에 `pre-push` 소스가 없어 `make setup-hooks` 가 정상 동작하면서 아무것도 설치하지 않았다. 훅은 첫머리에서 `unset GIT_DIR GIT_WORK_TREE` 한다 (#1314/#1318) — linked worktree 에서 git 이 주입하는 이 변수가 남으면 게이트가 push 하는 트리가 아니라 메인 체크아웃을 검사한다 (worktree 의 위반이 조용히 통과하고, 메인의 무관한 상태로 false-block 도 난다). **Test:** `tests/test_pre_push_hook.py` — 훅을 grep 하지 않고 임시 레포에서 **실행**해 exit code 를 본다(게이트 rc 0/1 양방향 + 게이트 부재 + 인터프리터 부재 + 오염 env 2종 + linked-worktree 실제 push).

**PreToolUse hook** blocks: `import sqlite3` outside `nuri/core/db/connection.py`, `git push --force` / `reset --hard` / `clean -f`, privacy ticker+PnL inline writes (`scripts/verify/check_privacy_leak.py --message --quiet`).

> ⚠️ 훅 안에서 stdin payload 를 다시 뱉을 땐 **`printf '%s' "$INPUT"` 만** — `echo` 금지.
> macOS `/bin/sh` 는 `xpg_echo` 가 켜진 bash 3.2 라 `echo` 가 **JSON 안의 `\n` 을 실제
> 개행으로 펼친다**. `new_string` 은 거의 항상 여러 줄이므로 JSON 이 깨지고 → jq 실패 →
> 변수 공백 → 가드가 **exit 0 으로 통과**한다. 차단이 아니라 침묵이라 아무 신호가 없다:
> 이 한 단어 때문에 sqlite3 / privacy 훅 2개가 #229(2026-04-13)부터 **3.5개월간 무력**이었고,
> 그동안 이 문서의 "blocks" 문장은 거짓이었다 (2026-07-29 `/doctor` 발견). 나머지 훅 3개는
> stdin 을 jq 로 직접 파이프해 왕복이 없어 영향 없었다.
> 같은 이유로 훅 본문은 **POSIX sh 만** 쓴다 — `[[ ]]` 는 dash 에서 조건절째 죽어 또 조용히
> exit 0 이 된다. 파일 매칭은 `case ... in` 으로. (macOS `/bin/sh` 는 bash 라 로컬에선 안 터지고
> Linux 에서만 터진다.)
> **Test:** `tests/test_hook_guard_execution.py` — 훅 명령을 grep 하지 않고 **셸로 실행**해 exit
> code 를 본다(위반 2 / 허용 0). 셸 2종을 돌린다: `bash -O xpg_echo`(macOS `/bin/sh` 등가 —
> `echo` 회귀 축)와 `dash`(bashism 축). 카나리아는 *개행을 품은* payload 다 — 단행 payload 는
> `echo` 로도 살아남아 회귀가 조용히 통과한다. mutation 실측: `printf`→`echo` 4 FAIL,
> `case`→`[[ ]]` 3 FAIL, 단행 payload 는 양쪽 mutant 에서 PASS.

**PostToolUse**: `datetime.now()` block (exit 1 surfaces to Claude), ruff advisory.

**pre-commit** (`scripts/hooks/pre-commit`, installed by the same `make setup-hooks`): 스테이지된 `.py` 에 `ruff check --fix` **+ `ruff format`**, `frontend/` 의 `.ts/.tsx/.js/.jsx` 에 `eslint --fix` 를 돌리고 **결과를 다시 스테이징한다.** 실패해도 커밋을 막지 않는다(advisory). 결과: 훅 도입 이전 포맷으로 남아 있던 파일을 처음 건드리면 **자기 변경보다 훨씬 큰 기계적 diff** 가 같이 커밋된다. 이건 스코프 크립이 아니라 레포 도구의 동작이니, 리뷰어에게 그렇게 설명하고 `git show -w` 로 걸러 읽게 할 것.

**CI gates** (every PR): `privacy-scan`, `pr-discipline` (commits ≤ 3 — escape `scope-expand-approved` label), test regression + Codecov 1% relative, `security-scan` (Trivy CRITICAL), `Doc Count Drift Check` (`make verify-doc-counts`).

**Playwright e2e — `frontend-e2e` job 으로 배선됨 (#1234).** `frontend/e2e/` 10 파일 89 테스트가 `main-ci-cd.yml` 의 `frontend-e2e` job 에서 PR 마다 돈다 — 프론트 **또는** 백엔드 변경 시 (스위트가 양쪽에 걸쳐 있다). 합성 seed DB(`scripts/dev/seed_e2e_db.py` → `NURI_DB_PATH`, #1240)를 만들고 playwright 가 두 서버를 직접 띄운다. 2026-08-26 이전에는 게이트가 아예 없었고, 그 결과 `410d385`(2026-05-04)가 `CONTEXT.SIEGE` 를 rename 하면서 vitest 만 고치고 e2e 는 두었는데 **3.5개월간 아무 신호가 없었다**(#1118). 배선의 선행 조건 2건: #1119(heavy-slot — 스위트가 자기 부하로 백엔드 포화)와 #1240(CI 에 populated DB 부재). Makefile · `scripts/verify/` 에는 여전히 없다 — 로컬에서는 대시보드를 건드리면 `cd frontend && npx playwright test` 로 손으로 돌릴 것. 상세는 `frontend/CLAUDE.md` "E2E (Playwright)".

## .claude/ 4-Layer Architecture (STRATEGY §5.10)

L1 CLAUDE.md (13 scoped + global) → L2 Skills (`.claude/skills/nuri-*/`, 6) → L3 Hooks (`.claude/settings.json` PreToolUse + PostToolUse) → L4 Agents (`.claude/agents/nuri-*.md`, 2). Slash commands: `.claude/commands/nuri-*.md` (8). Path-scoped + always-on rules: `.claude/rules/*.md`. `nuri-` prefix 만 git tracked — 머신별 개인 설치는 `.gitignore` 로 자동 ignored.
