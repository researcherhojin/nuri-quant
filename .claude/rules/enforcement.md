# Mechanical Enforcement

Hook config: `.claude/settings.json`. CI workflows: `.github/workflows/main-ci-cd.yml`. Pre-push: `scripts/pre_push_check.sh`.

**PreToolUse hook** blocks: `import sqlite3` outside `db.py`, `git push --force` / `reset --hard` / `clean -f`, privacy ticker+PnL inline writes (`scripts/verify/check_privacy_leak.py --message --quiet`).

**PostToolUse**: `datetime.now()` block (exit 1 surfaces to Claude), ruff advisory.

**CI gates** (every PR): `privacy-scan`, `pr-discipline` (commits ≤ 3 — escape `scope-expand-approved` label), test regression + Codecov 1% relative, `security-scan` (Trivy CRITICAL), `Doc Count Drift Check` (`make verify-doc-counts`).

## .claude/ 4-Layer Architecture (STRATEGY §5.10)

L1 CLAUDE.md (12 scoped + global) → L2 Skills (`.claude/skills/nuri-*/`, 6) → L3 Hooks (`.claude/settings.json` PreToolUse + PostToolUse) → L4 Agents (`.claude/agents/nuri-*.md`, 2). Slash commands: `.claude/commands/nuri-*.md` (8). Path-scoped + always-on rules: `.claude/rules/*.md`. `nuri-` prefix 만 git tracked — 머신별 개인 설치는 `.gitignore` 로 자동 ignored.
