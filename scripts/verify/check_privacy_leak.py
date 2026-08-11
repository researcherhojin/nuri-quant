#!/usr/bin/env python3
# cspell:ignore kakaopay mirae kiwoom
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

ROOT = Path(__file__).parent.parent.parent  # repo root (scripts/verify/X.py → 3 levels up)

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
    # KOFIA 회원사 보강 (#981) — #980 스윕에서 잡힌 증권사가 목록에 **없었다**.
    # 즉 파일 면제(구멍 1)를 막아도 이 목록이 얇아서 그대로 통과했을 것이다.
    # 회사명 자체는 공개 정보라 스캐너에 적는 건 안전하다.
    "신영증권",
    "교보증권",
    "현대차증권",
    "SK증권",
    "DB금융투자",
    "LS증권",
    "다올투자증권",
    "iM증권",
    "부국증권",
    "유진투자증권",
    "한양증권",
    "케이프투자증권",
    "상상인증권",
    "BNK투자증권",
    "하이투자증권",
    "한화투자증권",
    # ⚠️ `한국투자증권`(KIS) 은 여기 넣지 않는다 — 위 docstring 의 의도적 제외 결정.
    # Open API 통합 대상이라 `nuri/collectors/kis_*` 에 정당하게 등장하고, 자격증명은
    # 이름이 아니라 파일 패턴(`config/kis/*`)으로 막는다. 이번에 한 번 넣었다가
    # `kis_realtime.py` docstring 이 걸려서 되돌렸다.
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

# Ticker + PnL pattern — PR #202 leak signature.
# Example: "-34% (TEM), -22% (RKLB), -15% (TSLA)" or "PL +43% → +38%".
# Detects two tight patterns that in practice correlate with personal holdings
# + performance disclosure; loose `ticker + any signed %` patterns are too
# noisy (CAN SLIM rule text, HWM, SL/MDD abbreviations all trigger).
TICKER_PNL_PAREN = re.compile(r"[-+]\d+(?:\.\d+)?%\s*\(([A-Z]{2,5}(?:\.(?:KS|KQ))?)\)")
TICKER_PNL_ADJACENT = re.compile(r"\b([A-Z]{2,5}(?:\.(?:KS|KQ))?)\s{1,3}([-+]\d+(?:\.\d+)?%)")

# Ticker-lookalikes that are abbreviations, not equity symbols.
# Keep conservative — false negatives on obscure tickers are acceptable; the
# goal is catching personal portfolio mentions, not being a bourse registrar.
TICKER_FALSE_POSITIVES: frozenset[str] = frozenset(
    {
        # Strategy / analysis abbreviations
        "CAN",
        "SLIM",
        "HWM",
        "SEPA",
        "SL",
        "TP",
        "MDD",
        "PnL",
        "ROE",
        "ROA",
        "EPS",
        "PER",
        "PBR",
        "PEG",
        "PSR",
        "SMA",
        "EMA",
        "RSI",
        "MACD",
        "VIX",
        "POC",
        "BB",
        # Macro / econ
        "GDP",
        "CPI",
        "PPI",
        "PCE",
        "NFP",
        "FOMC",
        "FED",
        "ECB",
        "BOJ",
        "JOLTS",
        # Generic / units
        "USD",
        "KRW",
        "EUR",
        "GBP",
        "JPY",
        "CNY",
        "BTC",
        "ETH",
        "ETF",
        "CEO",
        "CFO",
        "CTO",
        "CMO",
        "COO",
        "API",
        "SDK",
        "CI",
        "CD",
        "PR",
        "SQL",
        "DB",
        "AI",
        "ML",
        "UI",
        "UX",
        "OS",
        "IT",
        "HR",
        "QA",
        "HTTP",
        "REST",
        "RPC",
        "DNS",
        "SSH",
        "TLS",
        "SSL",
        "URL",
        "URI",
        "JSON",
        "YAML",
        "CSV",
        "HTML",
        "CSS",
        "RAM",
        "CPU",
        "SSD",
        "GPU",
        "TTM",
        "YTD",
        "LTM",
        "QoQ",
        "YoY",
        "MoM",
        "MTD",
        "DTD",
        "ARR",
        "MRR",
        "NATO",
        "OECD",
        "IMF",
        "WTO",
        "SEC",
        "FINRA",
        "KOFIA",
        "KRX",
        # Trade verbs
        "BUY",
        "SELL",
        "HOLD",
        "LONG",
        "SHORT",
        # Misc
        "OK",
        "NO",
        "YES",
        "AM",
        "PM",
        "US",
        "UK",
        "EU",
        "KR",
        "JP",
        "CN",
        "RU",
        "Q1",
        "Q2",
        "Q3",
        "Q4",
        "H1",
        "H2",
    }
)

# Allow-list — **파일 전체가 아니라 카테고리 단위** (#981).
#
# 예전엔 경로 하나가 그 파일의 **모든** 규칙을 껐다. 그래서 `docs/STRATEGY.md` 가
# "패턴 이름을 적을 수도 있어서" 라는 사유로 500줄 통째로 빠졌고, 실제로는 451행의
# 증권사명 + 연금 보유 3종이 거기 숨어 있었다. `test_held_add_mode.py` 도 사유는
# "다계좌 NVDA/MSFT 시나리오" 인데 정작 가려진 건 픽스처 9곳의 증권사명이었다 —
# **적어둔 사유와 실제로 면제된 것이 달랐다.**
#
# 이제 값은 그 경로에서 끌 규칙의 집합이다. `ALL` 은 스캐너 자신처럼 세 카테고리를
# 전부 문서화하는 파일에만 쓴다. 사유에 적은 카테고리만 끄면, 사유 밖의 유출은
# 계속 걸린다.
ALL_CATEGORIES: frozenset[str] = frozenset({"broker_name", "suspect_numeric", "ticker_pnl"})

ALLOWLIST: dict[str, frozenset[str]] = {
    # 스캐너 본체와 그 테스트 — 세 카테고리의 패턴을 전부 적어 둔다.
    "scripts/verify/check_privacy_leak.py": ALL_CATEGORIES,
    "tests/scripts/test_check_privacy_leak.py": ALL_CATEGORIES,
    # E3 #579 — privacy gate 테스트가 탐지를 검증하려면 leak 픽스처가 필요하다.
    "tests/agents/test_discord_outbox.py": frozenset({"ticker_pnl", "broker_name"}),
    # #518 phase 2a — 다계좌 시나리오라 ticker+PnL 조합만. 증권사명은 **면제 아님**
    # (예전에 여기로 9곳이 새 나갔다).
    "tests/trading/recommend/test_held_add_mode.py": frozenset({"ticker_pnl"}),
    # #596 Phase 1 — gate lock-test 가 ticker+PnL 조합을 쓴다.
    "tests/alerts/test_postmarket_brief.py": frozenset({"ticker_pnl"}),
    # 정책 문서 — 플레이스홀더 이름을 가이드로 인용한다. 숫자·티커는 계속 검사.
    "CONTRIBUTING.md": frozenset({"broker_name"}),
    "SECURITY.md": frozenset({"broker_name"}),
    # 스캔 대상이 아닌 경로.
    ".claude/projects/": ALL_CATEGORIES,
    "node_modules/": ALL_CATEGORIES,
    ".git/": ALL_CATEGORIES,
    ".venv/": ALL_CATEGORIES,
    "frontend/package-lock.json": ALL_CATEGORIES,
}

# 줄 단위 탈출구 — 파일을 통째로 끄지 않고 그 줄만 면제한다.
#   `<something>  # privacy-allow: broker_name`  또는  `# privacy-allow`(전 카테고리)
# 파일 면제를 좁히면서 정당한 예외를 남길 수단이 필요했다 (#981).
_INLINE_ALLOW = re.compile(r"privacy-allow(?::\s*([a-z_,\s]+))?")


def line_allows(line: str, category: str) -> bool:
    """그 줄에 면제 마커가 있고 이 카테고리를 덮는가."""
    m = _INLINE_ALLOW.search(line)
    if not m:
        return False
    cats = m.group(1)
    if not cats:
        return True
    return category in {c.strip() for c in cats.split(",")}


@dataclass
class Finding:
    file: Path
    line: int
    pattern: str
    snippet: str
    category: str  # "broker_name" | "suspect_numeric" | "ticker_pnl"


def is_allowlisted(path: Path, category: str | None = None) -> bool:
    """이 경로에서 `category` 가 면제되는가. category=None 이면 '전 카테고리 면제' 인지.

    예전 시그니처는 경로만 받아 **파일 전체**를 껐다 (#981). 호출부가 카테고리를
    넘기지 않으면 ALL 면제인 경로에서만 True — 좁아진 쪽으로 기본값을 둔다.
    """
    try:
        rel = str(path.relative_to(ROOT)) if path.is_absolute() else str(path)
    except ValueError:
        # Path is outside the repo (e.g., /tmp/* in tests) — never allowlisted.
        return False
    for prefix, cats in ALLOWLIST.items():
        if rel.startswith(prefix.rstrip("/")):
            if category is None:
                return cats == ALL_CATEGORIES
            if category in cats:
                return True
    return False


def scan_text_for_brokers(text: str, source: Path | str = "<input>") -> list[Finding]:
    """Detect broker names in text. Used by both file scanner and stream mode."""
    findings: list[Finding] = []
    src_path = source if isinstance(source, Path) else Path(str(source))
    for ln_no, line in enumerate(text.splitlines(), start=1):
        for pat in BROKER_NAMES_KO:
            if pat in line:
                findings.append(
                    Finding(
                        file=src_path,
                        line=ln_no,
                        pattern=pat,
                        snippet=line.strip()[:120],
                        category="broker_name",
                    )
                )
        line_lower = line.lower()
        for pat in BROKER_NAMES_EN:
            if pat.lower() in line_lower:
                findings.append(
                    Finding(
                        file=src_path,
                        line=ln_no,
                        pattern=pat,
                        snippet=line.strip()[:120],
                        category="broker_name",
                    )
                )
    return findings


def scan_file_for_brokers(path: Path) -> list[Finding]:
    """Find any broker name occurrence in a file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return []  # binary or missing — skip
    return scan_text_for_brokers(text, source=path)


def scan_text_for_numerics(text: str, source: Path | str = "<input>") -> list[Finding]:
    """Detect large monetary literals (>= 1M) co-located with money-keys."""
    findings: list[Finding] = []
    src_path = source if isinstance(source, Path) else Path(str(source))
    numeric_pat = re.compile(r"\b(\d{7,})\b")
    for ln_no, line in enumerate(text.splitlines(), start=1):
        if not any(key in line for key in SUSPECT_NUMERIC_KEYS):
            continue
        for match in numeric_pat.finditer(line):
            value = int(match.group(1))
            if value < 1_000_000:
                continue
            if value % 1_000_000 == 0 and value <= 100_000_000:
                continue
            findings.append(
                Finding(
                    file=src_path,
                    line=ln_no,
                    pattern=str(value),
                    snippet=line.strip()[:120],
                    category="suspect_numeric",
                )
            )
    return findings


def scan_file_for_numerics(path: Path) -> list[Finding]:
    """File wrapper around scan_text_for_numerics."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return []
    return scan_text_for_numerics(text, source=path)


def gate_text(text: str, source: Path | str = "<stream>") -> list[Finding]:
    """E3 #579 — single-call privacy gate for agent transcripts.

    Aggregates all 4 categories (broker_name / suspect_numeric / ticker_pnl)
    on a text chunk before publishing to a Discord agent channel. Used by
    both `--stream` CLI mode and `stage_agent_dev_log` runtime gate.
    """
    return (
        scan_text_for_brokers(text, source)
        + scan_text_for_numerics(text, source)
        + scan_text_for_ticker_pnl(text, source)
    )


def scan_text_for_ticker_pnl(text: str, source: Path | str = "<input>") -> list[Finding]:
    """Detect ticker + PnL co-occurrence (PR #202 leak signature).

    Matches:
    - `-34% (TEM)` — signed % followed by ticker in parens
    - `PL +43%` — ticker directly followed by signed %

    Uses TICKER_FALSE_POSITIVES to exclude abbreviations (HWM, SL, MDD, etc.).
    """
    findings: list[Finding] = []
    file_path = source if isinstance(source, Path) else Path(str(source))
    for ln_no, line in enumerate(text.splitlines(), start=1):
        for m in TICKER_PNL_PAREN.finditer(line):
            ticker = m.group(1)
            if ticker in TICKER_FALSE_POSITIVES:
                continue
            findings.append(
                Finding(
                    file=file_path,
                    line=ln_no,
                    pattern=f"%({ticker})",
                    snippet=line.strip()[:120],
                    category="ticker_pnl",
                )
            )
        for m in TICKER_PNL_ADJACENT.finditer(line):
            ticker = m.group(1)
            if ticker in TICKER_FALSE_POSITIVES:
                continue
            findings.append(
                Finding(
                    file=file_path,
                    line=ln_no,
                    pattern=f"{ticker} {m.group(2)}",
                    snippet=line.strip()[:120],
                    category="ticker_pnl",
                )
            )
    return findings


def scan_file_for_ticker_pnl(path: Path) -> list[Finding]:
    """File wrapper around scan_text_for_ticker_pnl."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return []
    return scan_text_for_ticker_pnl(text, source=path)


def scan_path(path: Path) -> list[Finding]:
    """Scan one file for all categories. Skips allowlisted/binary."""
    if is_allowlisted(path):  # 전 카테고리 면제인 경로만 통째로 건너뛴다
        return []
    if not path.is_file():
        return []
    if path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".pyc", ".woff", ".woff2", ".ttf", ".eot", ".ico"}:
        return []
    # 카테고리별로 따로 묻는다 (#981). 한 파일이 한 규칙만 면제받을 수 있어야
    # "사유에 적은 것" 과 "실제로 가려지는 것" 이 어긋나지 않는다.
    out: list[Finding] = []
    if not is_allowlisted(path, "broker_name"):
        out += scan_file_for_brokers(path)
    if not is_allowlisted(path, "suspect_numeric"):
        out += scan_file_for_numerics(path)
    if not is_allowlisted(path, "ticker_pnl"):
        out += scan_file_for_ticker_pnl(path)
    # 줄 단위 면제 마커 적용 — 파일 면제를 좁힌 대신 남긴 정당한 탈출구.
    lines = _read_lines(path)
    return [f for f in out if not (0 < f.line <= len(lines) and line_allows(lines[f.line - 1], f.category))]


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []


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

    print(f"{RED}✗ {len(findings)} potential leak(s) in {len(by_file)} file(s):{NC}\n")

    category_label = {
        "broker_name": "broker name",
        "suspect_numeric": "suspect $",
        "ticker_pnl": "ticker+PnL",
    }

    for file_path, file_findings in by_file.items():
        try:
            rel = file_path.relative_to(ROOT)
        except ValueError:
            rel = file_path
        print(f"  {CYAN}{rel}{NC}")
        for f in file_findings:
            cat_label = category_label.get(f.category, f.category)
            print(f"    line {f.line:5d}  [{cat_label}]  {YELLOW}{f.pattern}{NC}  →  {f.snippet}")
        print()

    print(
        f"{YELLOW}Action: replace real broker names with placeholders "
        f"(Brokerage Alpha/Beta), use round-number placeholders for monetary "
        f"fields, and avoid disclosing ticker + PnL combinations in commit "
        f"messages / PR bodies. See docs/STRATEGY.md §4.4.{NC}"
    )


def iter_unpushed_commit_messages() -> list[tuple[str, str]]:
    """Return [(sha, message)] for commits on current branch that are not yet on origin/main.

    Used by pre_push_check.sh to scan commit messages before pushing — catches
    the PR #202 class of leak (ticker + PnL in commit body) before it hits
    git history permanently.
    """
    try:
        shas = subprocess.run(
            ["git", "log", "--format=%H", "origin/main..HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
    except subprocess.CalledProcessError:
        return []
    out: list[tuple[str, str]] = []
    for sha in shas:
        try:
            msg = subprocess.run(
                ["git", "log", "-1", "--format=%B", sha],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except subprocess.CalledProcessError:
            continue
        out.append((sha, msg))
    return out


def main() -> int:
    description = (__doc__ or "").split("\n", 1)[0]
    parser = argparse.ArgumentParser(description=description)
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
        "--message",
        action="store_true",
        help="Read text from stdin and scan it (for commit-msg / PR body hooks)",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Read agent transcript from stdin (line-buffered) and gate-check all 4 "
        "categories (broker / numeric / ticker_pnl). Exit 2 on any finding "
        "(stricter than commit-msg's exit 1) so callers can distinguish from "
        "lint-level failures. Used by stage_agent_dev_log() before publish.",
    )
    parser.add_argument(
        "--unpushed-commits",
        action="store_true",
        help="Scan commit messages of unpushed commits (origin/main..HEAD)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="No output on success — only print on findings",
    )
    args = parser.parse_args()

    findings: list[Finding] = []

    if args.stream:
        text = sys.stdin.read()
        findings.extend(gate_text(text, source="<stream>"))
        if findings:
            print_findings(findings)
            return 2
        if not args.quiet:
            print("✓ stream privacy gate clean", file=sys.stderr)
        return 0
    elif args.message:
        text = sys.stdin.read()
        findings.extend(scan_text_for_ticker_pnl(text, source="<stdin>"))
    elif args.unpushed_commits:
        for sha, msg in iter_unpushed_commit_messages():
            for f in scan_text_for_ticker_pnl(msg, source=f"<commit:{sha[:8]}>"):
                findings.append(f)
    else:
        if args.diff:
            targets = iter_staged_diff_files()
        elif args.paths:
            targets = args.paths
        else:
            targets = iter_repo_files()
        for path in targets:
            findings.extend(scan_path(path))

    if findings or not args.quiet:
        print_findings(findings)

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
