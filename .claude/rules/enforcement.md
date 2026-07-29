# Mechanical Enforcement

Hook config: `.claude/settings.json`. CI workflows: `.github/workflows/main-ci-cd.yml`. Pre-push: `scripts/verify/pre_push_check.sh`.

**PreToolUse hook** blocks: `import sqlite3` outside `nuri/core/db/connection.py`, `git push --force` / `reset --hard` / `clean -f`, privacy ticker+PnL inline writes (`scripts/verify/check_privacy_leak.py --message --quiet`).

> ⚠️ 훅 안에서 stdin payload 를 다시 뱉을 땐 **`printf '%s' "$INPUT"` 만** — `echo` 금지.
> macOS `/bin/sh` 는 `xpg_echo` 가 켜진 bash 3.2 라 `echo` 가 **JSON 안의 `\n` 을 실제
> 개행으로 펼친다**. `new_string` 은 거의 항상 여러 줄이므로 JSON 이 깨지고 → jq 실패 →
> 변수 공백 → 가드가 **exit 0 으로 통과**한다. 차단이 아니라 침묵이라 아무 신호가 없다:
> 이 한 단어 때문에 sqlite3 / privacy 훅 2개가 #229(2026-04-13)부터 **3.5개월간 무력**이었고,
> 그동안 이 문서의 "blocks" 문장은 거짓이었다 (2026-07-29 `/doctor` 발견). 나머지 훅 3개는
> stdin 을 jq 로 직접 파이프해 왕복이 없어 영향 없었다.
> **Test:** `tests/test_hook_guard_execution.py` — 훅 명령을 grep 하지 않고 `sh -c` + stdin JSON 으로
> **실행**해 exit code 를 본다(위반 2 / 허용 0). 카나리아는 *개행을 품은* payload 다 — 단행
> payload 는 `echo` 로도 살아남아 회귀가 조용히 통과한다 (mutation 실측: 단행 PASS, 개행 FAIL).

**PostToolUse**: `datetime.now()` block (exit 1 surfaces to Claude), ruff advisory.

**CI gates** (every PR): `privacy-scan`, `pr-discipline` (commits ≤ 3 — escape `scope-expand-approved` label), test regression + Codecov 1% relative, `security-scan` (Trivy CRITICAL), `Doc Count Drift Check` (`make verify-doc-counts`).

## .claude/ 4-Layer Architecture (STRATEGY §5.10)

L1 CLAUDE.md (13 scoped + global) → L2 Skills (`.claude/skills/nuri-*/`, 6) → L3 Hooks (`.claude/settings.json` PreToolUse + PostToolUse) → L4 Agents (`.claude/agents/nuri-*.md`, 2). Slash commands: `.claude/commands/nuri-*.md` (8). Path-scoped + always-on rules: `.claude/rules/*.md`. `nuri-` prefix 만 git tracked — 머신별 개인 설치는 `.gitignore` 로 자동 ignored.
