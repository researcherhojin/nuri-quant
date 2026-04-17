#!/usr/bin/env bash
# codex_review.sh — Wrap `codex exec` to archive the prompt + response.
#
# Every codex review that goes through this script gets logged to
# codex-reviews/PR<pr>-round<round>-<timestamp>.md so we can audit
# what the two AIs actually said to each other. The raw codex rollout
# JSONL at ~/.codex/sessions/YYYY/MM/DD/ stays as the source of truth;
# this is a human-readable excerpt scoped to a PR review.
#
# Prompt drafts: store under `codex-reviews/prompts/` (gitignored) — keeps
# prompt sources project-local + accumulating across sessions rather than
# scattered in /tmp/.
#
# Timebox default: prompts should request a 3-5 minute timebox unless the
# task genuinely spans many files. Long prompts produce flaky results.
#
# Usage:
#   scripts/codex_review.sh <pr> <round> "<prompt>"
#   scripts/codex_review.sh <pr> <round> < codex-reviews/prompts/<name>.txt
#
# Example:
#   scripts/codex_review.sh 376 1 < codex-reviews/prompts/PR376-round1.txt

set -euo pipefail

PR="${1:?missing PR number — usage: scripts/codex_review.sh <pr> <round> [prompt]}"
ROUND="${2:?missing round number}"
PROMPT="${3:-}"

if [ -z "$PROMPT" ]; then
  if [ -t 0 ]; then
    echo "error: provide prompt as third arg or via stdin" >&2
    exit 1
  fi
  PROMPT="$(cat)"
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
OUT_DIR="$REPO_ROOT/codex-reviews"
mkdir -p "$OUT_DIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$OUT_DIR/PR${PR}-round${ROUND}-${TS}.md"

{
  echo "# PR #${PR} codex review — Round ${ROUND}"
  echo
  echo "- Timestamp: ${TS}"
  echo "- Branch: $(git branch --show-current 2>/dev/null || echo unknown)"
  echo "- HEAD: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo
  echo "## Prompt"
  echo
  echo '```'
  printf '%s\n' "$PROMPT"
  echo '```'
  echo
  echo "## Response"
  echo
} > "$OUT"

# Stream codex output to both terminal and the archive file. We intentionally
# do NOT use `--output-last-message` — that captures only the final text and
# drops reasoning / function calls. For full fidelity, read the rollout JSONL
# at ~/.codex/sessions/... instead.
#
# Capture codex's own exit code (tee would otherwise mask it via pipefail).
set +e
codex exec --sandbox read-only --skip-git-repo-check "$PROMPT" 2>&1 | tee -a "$OUT"
CODEX_EXIT=${PIPESTATUS[0]}
set -e

{
  echo
  echo "---"
  echo "Exit code: ${CODEX_EXIT}"
} >> "$OUT"

echo
echo "==> Archived: $OUT"
