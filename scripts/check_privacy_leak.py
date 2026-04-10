#!/usr/bin/env python3
"""scripts/check_privacy_leak.py — block personal financial data from leaking
into git-tracked code (#138).

Why this exists
---------------
PR #111 (commit aab83d6) committed test fixtures that included real broker
names and a real total_invested value. PR #113 sanitized some of it but
missed broker names + the suspect ₩48,323,344 amount. The current sanitize
in PR #147 (#138 Stage 1) cleans the tree, but without a mechanical gate
the same class of leak will recur.

This scanner runs in three places:
1. `scripts/pre_push_check.sh` — local pre-push gate
2. `.github/workflows/main-ci-cd.yml` — CI gate on every PR
3. CLI manual: `python scripts/check_privacy_leak.py`

Patterns
--------
1. Real broker names (Korean retail brokerages the project owner could use):
   카카오페이, 미래에셋, 키움증권, 한국투자증권, 삼성증권, NH투자증권,
   토스증권, KB증권, 신한투자증권, 하나증권, 메리츠증권, 유안타증권,
   대신증권, 이베스트, 흥국, IBK투자
   plus their romanized variants (kakaopay, mirae, kiwoom, ...)

2. Suspect-large numeric literals (≥7 digits) that look like real KRW
   total_invested or cash balances. To avoid false positives on
   legitimate numerics (test row counts, IDs, prices in won) we ONLY
   flag literals >= 1_000_000 in test files AND check the surrounding
   context for keys like total_invested, cash_balance, deposit, withdraw.

Allow-list
----------
- `config/portfolio.yaml` is gitignored — never scanned
- `config/portfolio.example.yaml` uses generic placeholders by design
- `nuri/` source code legitimately references public US tickers (TSLL,
  TQQQ, etc.) for leverage_ban gate logic — these are NOT broker names
- This file itself documents the patterns and is allow-listed

Exit codes
----------
- 0: clean
- 1: leak detected (block commit/push/CI)

Usage
-----
    python scripts/check_privacy_leak.py                    # scan whole repo
    python scripts/check_privacy_leak.py path/to/file.py    # scan specific files
    python scripts/check_privacy_leak.py --diff             # scan staged diff only
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ANSI colors
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
CYAN = "\033[0;36m"
NC = "\033[0m"


# ═══════════════════════════════════════════════════════
# Patterns
# ═══════════════════════════════════════════════════════

# Korean retail brokerages — case-insensitive substring match.
# Source: KOFIA registered broker-dealers (2026) + romanized aliases.
#
# 한국투자증권 (KIS) is intentionally OMITTED — it appears legitimately in
# the codebase as an Open API integration target (`nuri/collectors/kis_*`,
# `docs/KIS_INTEGRATION.md`). Personal account credentials live at
# `config/kis/kis_devlp.yaml` (gitignored by `config/kis/*` directory pattern
# AND by `**/kis_devlp.yaml` filename pattern). Legacy `~/KIS/` is auto-detected
# as fallback. If a KIS credential leaks, it would be via the file pattern,
# not the broker name.
BROKER_NAMES_KO: tuple[str, ...] = (
    "카카오페이",
    "미래에셋",
    "키움증권",
    "삼성증권",
    "NH투자증권",
    "토스증권",
    "KB증권",
    "신한투자증권",
    "하나증권",
    "메리츠증권",
    "유안타증권",
    "대신증권",
    "이베스트투자증권",
    "흥국증권",
    "IBK투자증권",
)

# Romanized aliases — case-insensitive substring match.
# Verified absent from the codebase outside this scanner + its tests, so
# substring match is safe. Each entry is specific enough that false positives
# are unlikely (e.g. `kiwoom` is the only Korean word containing that ngram;
# `toss_securities` requires the underscore to avoid matching the design
# system or RxJS Tossing actions).
BROKER_NAMES_EN: tuple[str, ...] = (
    "kakaopay",
    "mirae",
    "kiwoom",
    "samsung_securities",
    "nh_invest",
    "toss_securities",
    "shinhan_invest",
    "hana_securities",
    "meritz_securities",
)

# Suspect numeric context — large literals near these key names = real money.
SUSPECT_NUMERIC_KEYS: tuple[str, ...] = (
    "total_invested",
    "cash_balance",
    "deposit",
    "withdraw",
    "principal",
    "net_worth",
    "buying_power",
)

# Allow-list: paths the scanner should NEVER block on.
ALLOWLIST_PATHS: tuple[str, ...] = (
    "scripts/check_privacy_leak.py",      # this file (documents patterns)
    "tests/scripts/test_check_privacy_leak.py",  # tests for this file (moved from top-level in #163)
    "docs/STRATEGY.md",                   # may codify pattern names
    "CONTRIBUTING.md",                    # references placeholder names as guidance
    "SECURITY.md",                        # references privacy policy
    ".claude/projects/",                  # private memory dir (git-ignored anyway)
    "node_modules/",
    ".git/",
    ".venv/",
    "frontend/package-lock.json",         # npm hash collisions look like words
)


@dataclass
class Finding:
    file: Path
    line: int
    pattern: str
    snippet: str
    category: str  # "broker_name" | "suspect_numeric"


def is_allowlisted(path: Path) -> bool:
    """True if path matches any allowlisted prefix."""
    try:
        rel = str(path.relative_to(ROOT)) if path.is_absolute() else str(path)
    except ValueError:
        # Path is outside the repo (e.g., /tmp/* in tests) — never allowlisted.
        return False
    return any(rel.startswith(p.rstrip("/")) for p in ALLOWLIST_PATHS)


def scan_file_for_brokers(path: Path) -> list[Finding]:
    """Find any broker name occurrence in a file."""
    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return findings  # binary or missing — skip

    lines = text.splitlines()
    for ln_no, line in enumerate(lines, start=1):
        # Korean substring (case-insensitive doesn't matter for hangul)
        for pat in BROKER_NAMES_KO:
            if pat in line:
                findings.append(Finding(
                    file=path, line=ln_no, pattern=pat,
                    snippet=line.strip()[:120], category="broker_name",
                ))
        # English: case-insensitive substring (variable names like
        # `kakaopay_main` would otherwise escape a \b regex because `_` is
        # a word character).
        line_lower = line.lower()
        for pat in BROKER_NAMES_EN:
            if pat.lower() in line_lower:
                findings.append(Finding(
                    file=path, line=ln_no, pattern=pat,
                    snippet=line.strip()[:120], category="broker_name",
                ))
    return findings


def scan_file_for_numerics(path: Path) -> list[Finding]:
    """Find large numeric literals (>= 1M) co-located with money-keys.

    To minimize false positives we require the SAME line to contain both
    a SUSPECT_NUMERIC_KEYS hit and a numeric literal >= 1_000_000.
    """
    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return findings

    numeric_pat = re.compile(r"\b(\d{7,})\b")  # >= 7 digits = >= 1,000,000

    for ln_no, line in enumerate(text.splitlines(), start=1):
        if not any(key in line for key in SUSPECT_NUMERIC_KEYS):
            continue
        for match in numeric_pat.finditer(line):
            value = int(match.group(1))
            if value < 1_000_000:
                continue
            # Allow round-number placeholders explicitly (1_000_000, 10_000_000, ...)
            if value % 1_000_000 == 0 and value <= 100_000_000:
                continue
            findings.append(Finding(
                file=path, line=ln_no, pattern=str(value),
                snippet=line.strip()[:120], category="suspect_numeric",
            ))
    return findings


def scan_path(path: Path) -> list[Finding]:
    """Scan one file for all categories. Skips allowlisted/binary."""
    if is_allowlisted(path):
        return []
    if not path.is_file():
        return []
    if path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".pyc",
                       ".woff", ".woff2", ".ttf", ".eot", ".ico"}:
        return []
    return scan_file_for_brokers(path) + scan_file_for_numerics(path)


def iter_repo_files() -> list[Path]:
    """All git-tracked files (respects .gitignore automatically)."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return [ROOT / line for line in result.stdout.splitlines() if line]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return list(ROOT.rglob("*"))


def iter_staged_diff_files() -> list[Path]:
    """Files in git's staged diff (used by --diff mode for pre-commit gate)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return [ROOT / line for line in result.stdout.splitlines() if line]
    except subprocess.CalledProcessError:
        return []


def print_findings(findings: list[Finding]) -> None:
    if not findings:
        print(f"{GREEN}✓ No personal financial data leaks detected.{NC}")
        return

    by_file: dict[Path, list[Finding]] = {}
    for f in findings:
        by_file.setdefault(f.file, []).append(f)

    print(f"{RED}✗ {len(findings)} potential leak(s) in "
          f"{len(by_file)} file(s):{NC}\n")

    for file_path, file_findings in by_file.items():
        try:
            rel = file_path.relative_to(ROOT)
        except ValueError:
            rel = file_path
        print(f"  {CYAN}{rel}{NC}")
        for f in file_findings:
            cat_label = "broker name" if f.category == "broker_name" else "suspect $"
            print(f"    line {f.line:5d}  [{cat_label}]  "
                  f"{YELLOW}{f.pattern}{NC}  →  {f.snippet}")
        print()

    print(f"{YELLOW}Action: replace real broker names with placeholders "
          f"(Brokerage Alpha/Beta) and use round-number placeholders "
          f"for monetary fields. See docs/STRATEGY.md §4.4.{NC}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Specific files to scan (default: whole repo)",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Scan only files in git staged diff (for pre-commit hook)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="No output on success — only print on findings",
    )
    args = parser.parse_args()

    if args.diff:
        targets = iter_staged_diff_files()
    elif args.paths:
        targets = args.paths
    else:
        targets = iter_repo_files()

    findings: list[Finding] = []
    for path in targets:
        findings.extend(scan_path(path))

    if findings or not args.quiet:
        print_findings(findings)

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
