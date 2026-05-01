#!/usr/bin/env bash
# Idempotent installer for repo-tracked git hooks.
# Symlinks .git/hooks/* → scripts/hooks/* so hook updates ride with the repo.
# Safe to re-run: replaces existing symlinks, refuses to clobber non-symlink hooks.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK_SRC_DIR="$REPO_ROOT/scripts/hooks"
HOOK_DST_DIR="$REPO_ROOT/.git/hooks"

if [ ! -d "$HOOK_SRC_DIR" ]; then
    echo "error: $HOOK_SRC_DIR missing" >&2
    exit 1
fi

mkdir -p "$HOOK_DST_DIR"
installed=0
skipped=0

for src in "$HOOK_SRC_DIR"/*; do
    [ -f "$src" ] || continue
    name=$(basename "$src")
    dst="$HOOK_DST_DIR/$name"
    chmod +x "$src"

    if [ -L "$dst" ] || [ ! -e "$dst" ]; then
        ln -sf "$src" "$dst"
        echo "  ✓ $name → scripts/hooks/$name"
        installed=$((installed + 1))
    else
        echo "  ⚠ $name exists as regular file — skipped (remove manually to install)"
        skipped=$((skipped + 1))
    fi
done

echo ""
echo "Installed $installed hook(s), skipped $skipped."
echo "Bypass any hook with: git commit --no-verify"
