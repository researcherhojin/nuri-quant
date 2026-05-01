#!/usr/bin/env python3
"""scripts/check_drift.py — Analyze working tree drift vs current branch.

Background: this session lost ~30 minutes to "drift bugs" — a config or
source file modified in working tree but not committed, causing local
checks to use the modified version while CI uses the committed version.

Two known patterns from this session:
1. pyproject.toml had `per-file-ignores` only in working tree → local
   ruff passed, CI failed with 270 F401 errors.
2. nuri/llm/report.py had `OPENAI_API_KEY` only in working tree → local
   tests passed, CI failed with AttributeError.

This script catches such drift by:
1. Listing all uncommitted files (modified + untracked)
2. For each, checking if any COMMITTED file on the current branch
   imports/references it.
3. Warning if a committed file depends on an uncommitted file (= CI fails).

Usage:
    python scripts/check_drift.py                # report drift
    python scripts/check_drift.py --strict       # exit 1 if any drift risk
    python scripts/check_drift.py --silent       # only show summary line
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ANSI colors
GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[0;33m"
CYAN = "\033[0;36m"
NC = "\033[0m"


def git(*args: str) -> str:
    """Run a git command and return stdout."""
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout


def list_uncommitted() -> tuple[list[str], list[str]]:
    """Return (modified, untracked) file lists."""
    status = git("status", "--short")
    modified, untracked = [], []
    for line in status.splitlines():
        if not line.strip():
            continue
        flag, path = line[:2], line[3:].strip()
        if flag.startswith("??"):
            untracked.append(path)
        elif "M" in flag or "D" in flag or "A" in flag or "R" in flag:
            modified.append(path)
    return modified, untracked


def list_committed_files() -> list[Path]:
    """All Python/YAML/TOML/MD files tracked by git on current branch."""
    output = git("ls-files", "*.py", "*.yml", "*.yaml", "*.toml", "*.md")
    return [ROOT / p for p in output.splitlines() if p.strip()]


def file_to_module(path: str) -> str | None:
    """Convert nuri/foo/bar.py → nuri.foo.bar (None if not Python)."""
    if not path.endswith(".py") or path.endswith("__init__.py"):
        return None
    return path.removesuffix(".py").replace("/", ".")


def find_referencers(target: str, committed: list[Path]) -> list[Path]:
    """Find committed files that import/reference the target.

    Heuristic: substring match on module path or filename.
    """
    refs = []
    module = file_to_module(target)
    basename = Path(target).stem

    # Build regex patterns to match
    patterns = []
    if module:
        # `from nuri.foo.bar import` or `import nuri.foo.bar`
        patterns.append(rf"\bfrom\s+{re.escape(module)}\b")
        patterns.append(rf"\bimport\s+{re.escape(module)}\b")
    if basename and len(basename) > 3:  # avoid false positives on short names
        patterns.append(rf"\b{re.escape(basename)}\b")

    if not patterns:
        return refs

    combined = re.compile("|".join(patterns))
    for f in committed:
        if str(f.relative_to(ROOT)) == target:
            continue  # skip self
        try:
            if combined.search(f.read_text(errors="ignore")):
                refs.append(f)
        except OSError:
            continue
    return refs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 if any drift risk found")
    parser.add_argument("--silent", action="store_true",
                        help="only print summary line")
    args = parser.parse_args()

    modified, untracked = list_uncommitted()
    total = len(modified) + len(untracked)

    if args.silent:
        print(f"drift: {len(modified)} modified, {len(untracked)} untracked, total {total}")
        return 0 if total == 0 else (1 if args.strict else 0)

    print(f"\n{CYAN}━━━ Drift Check ━━━{NC}")
    print(f"  Modified:  {len(modified)}")
    print(f"  Untracked: {len(untracked)}")
    print(f"  Total:     {total}")

    if total == 0:
        print(f"\n{GREEN}✓ Clean working tree — no drift risk{NC}\n")
        return 0

    if total > 20:
        print(f"\n{RED}🚨 HIGH DRIFT ({total} files){NC}")
        print(f"{RED}   Each new commit risks invisible dependencies on uncommitted state.{NC}")
        print(f"{RED}   Strongly recommend committing before continuing.{NC}\n")
    elif total > 5:
        print(f"\n{YELLOW}⚠ Moderate drift ({total} files){NC}")
        print(f"{YELLOW}   Consider committing related work before adding new commits.{NC}\n")

    # Heavy analysis: find referencers (only for modified Python/config files)
    interesting = [
        f for f in modified
        if f.endswith((".py", ".toml", ".yml", ".yaml")) and not f.startswith("frontend/")
    ]
    if not interesting:
        print("  (no Python/config drift to analyze)\n")
        return 0

    print(f"\n{CYAN}━━━ Reference Analysis ━━━{NC}")
    print(f"  Checking {len(interesting)} modified file(s) for committed references...\n")

    committed = list_committed_files()
    risky_count = 0

    for f in interesting:
        refs = find_referencers(f, committed)
        if refs:
            risky_count += 1
            print(f"  {YELLOW}⚠ {f}{NC}")
            print(f"    referenced by {len(refs)} committed file(s):")
            for r in refs[:3]:
                print(f"      → {r.relative_to(ROOT)}")
            if len(refs) > 3:
                print(f"      → ... +{len(refs) - 3} more")
            print()

    if risky_count == 0:
        print(f"  {GREEN}✓ No committed files reference uncommitted changes — drift is isolated{NC}\n")
        return 0

    print(f"{RED}━━━ Drift Risk Summary ━━━{NC}")
    print(f"  {risky_count}/{len(interesting)} uncommitted files are referenced by committed code.")
    print("  CI may behave differently than local because committed code references state")
    print("  that doesn't exist on remote.\n")
    print("  Mitigation:")
    print("    1. Commit referenced files first (in a separate PR)")
    print("    2. Or rebase your branch onto a branch that includes them")
    print("    3. Or temporarily revert dependent code in your PR\n")

    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
