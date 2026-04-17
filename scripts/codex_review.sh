#!/usr/bin/env bash
# codex_review.sh — Wrap `codex exec` to archive the prompt + response.
#
# Every codex review that goes through this script gets logged to
# data/codex-reviews/PR<pr>-round<round>-<timestamp>.md so we can audit
# what the two AIs actually said to each other. The raw codex rollout
# JSONL at ~/.codex/sessions/YYYY/MM/DD/ stays as the source of truth;
# this is a human-readable excerpt scoped to a PR review.
#
# Usage:
#   scripts/codex_review.sh <pr> <round> "<prompt>"
#   scripts/codex_review.sh <pr> <round> < prompt.txt
#
# Example:
#   scripts/codex_review.sh 376 1 "Review diff between main and HEAD on \
#     branch phase2/a4-sell-catalyst. Also re-review PR #374 (A-3, merge \
#     SHA f0d0f82) as debt recovery per STRATEGY §4.3. Report P1/P2/LOW."

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
OUT_DIR="$REPO_ROOT/data/codex-reviews"
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
