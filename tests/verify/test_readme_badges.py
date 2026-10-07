"""README `## Tech Stack` 뱃지의 버전이 실제 설치 버전과 맞는다 (#1704).

뱃지는 메이저만 적는다(0.x 는 메이저.마이너 — `check_lock_major_bump.py` 가 0.x 의 마이너
상승을 메이저 경계로 보는 것과 같은 기준). 패치·마이너 bump 마다 README 를 고치게 하면
dependabot 자동 머지가 이 테스트에 막히고, 아무 검사 없이 두면 조용히 낡는다. 메이저 경계는
이미 사람 검토(`lock-bump-reviewed`)를 거치므로 그때 뱃지도 같이 고치면 된다.

양방향이다: 버전이 숫자인 뱃지가 아래 표에 없으면 FAIL(검사 밖 뱃지가 생기지 않게),
표에 있는데 README 에 없어도 FAIL(낡은 항목). 색 형식과 무관하게 읽고, 같은 라벨이 두 번 나오면 FAIL.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"

# 뱃지 라벨(shields 인코딩 그대로) → (출처, 패키지)
BADGES = {
    "Next.js": ("npm", "next"),
    "React": ("npm", "react"),
    "TypeScript": ("npm", "typescript"),
    "Tailwind_CSS": ("npm", "tailwindcss"),
    "Recharts": ("npm", "recharts"),
    "React_Flow": ("npm", "@xyflow/react"),
    "Zod": ("npm", "zod"),
    "Vitest": ("npm", "vitest"),
    "Testing_Library": ("npm", "@testing-library/react"),
    "Playwright": ("npm", "@playwright/test"),
    "ESLint": ("npm", "eslint"),
    "oxlint": ("npm", "oxlint"),
    "FastAPI": ("uv", "fastapi"),
    "Uvicorn": ("uv", "uvicorn"),
    "APScheduler": ("uv", "apscheduler"),
    "MCP": ("uv", "mcp"),
    "discord.py": ("uv", "discord-py"),
    "pandas": ("uv", "pandas"),
    "NumPy": ("uv", "numpy"),
    "TA--Lib": ("uv", "ta-lib"),
    "yfinance": ("uv", "yfinance"),
    "pykrx": ("uv", "pykrx"),
    "pytest": ("uv", "pytest"),
    "Ruff": ("uv", "ruff"),
    "Python": ("python-version", ""),
    "Node": ("ci-node", ""),
}

# 숫자지만 lock 에서 오지 않는 뱃지 — 이유와 함께 둔다
EXEMPT = {"SQLite": "SQLite 3 은 파일 형식 세대다. Python 표준 라이브러리 `sqlite3` 로 쓰며 lock 에 없다"}

# 버전 자리에 설명(`CI/CD`, `Enabled`)을 담은 뱃지는 숫자가 아니라 자연히 빠진다.
# 색은 형식을 가리지 않는다 — hex 6자리만 받으면 `-blue` · `-abc` 뱃지가 검사를 빠져나간다.
_BADGE = re.compile(r"img\.shields\.io/badge/((?:[^-]|--)+)-((?:[^-]|--)+)-[^?)\s-]+")


def _parse(section: str) -> dict[str, str]:
    """라벨 → 버전. 같은 라벨이 두 번 나오면 하나가 다른 하나를 가리므로 거부한다."""
    pairs = [(m.group(1), m.group(2)) for m in _BADGE.finditer(section)]
    labels = [label for label, _ in pairs]
    dupes = sorted({label for label in labels if labels.count(label) > 1})
    assert not dupes, f"README Tech Stack 에 같은 라벨 뱃지가 여러 개: {dupes}"
    return dict(pairs)


def _tech_stack_badges() -> dict[str, str]:
    text = README.read_text()
    return _parse(text[text.index("## Tech Stack") : text.index("\n## ", text.index("## Tech Stack") + 1)])


def _display(version: str) -> str:
    parts = version.split(".")
    return ".".join(parts[:2]) if parts[0] == "0" else parts[0]


def _installed(source: str, package: str) -> str:
    if source == "npm":
        lock = json.loads((REPO_ROOT / "frontend/package-lock.json").read_text())
        return _display(lock["packages"][f"node_modules/{package}"]["version"])
    if source == "uv":
        lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text())
        return _display(next(p["version"] for p in lock["package"] if p["name"] == package))
    if source == "python-version":
        return (REPO_ROOT / ".python-version").read_text().strip()
    workflow = (REPO_ROOT / ".github/workflows/main-ci-cd.yml").read_text()
    return re.search(r'NODE_VERSION:\s*"(\d+)"', workflow).group(1)


class TestTechStackBadges:
    def test_versions_match_what_is_installed(self):
        badges = _tech_stack_badges()
        wrong = {
            label: (badges[label], _installed(*BADGES[label]))
            for label in BADGES
            if label in badges and badges[label] != _installed(*BADGES[label])
        }
        assert not wrong, f"README 뱃지 버전 (적힌 값, 설치 값): {wrong}"

    def test_every_numeric_badge_is_checked_and_every_entry_is_used(self):
        badges = _tech_stack_badges()
        numeric = {label for label, version in badges.items() if re.fullmatch(r"\d+(\.\d+)?", version)}
        assert numeric - set(BADGES) - set(EXEMPT) == set(), "검사 표에 없는 버전 뱃지"
        assert (set(BADGES) | set(EXEMPT)) - set(badges) == set(), "README 에 없는 낡은 표 항목"

    def test_parser_sees_any_color_format_and_rejects_duplicates(self):
        # Codex #1704 r1: 이름 색·3자리 색 뱃지가 빠져나갔고, 중복 라벨은 뒤의 것이 앞의 틀린 값을 가렸다
        badges = _parse(
            "![a](https://img.shields.io/badge/Unknown-999-blue) ![b](https://img.shields.io/badge/Other-998-abc)"
        )
        assert badges == {"Unknown": "999", "Other": "998"}
        with pytest.raises(AssertionError, match="React"):
            _parse("img.shields.io/badge/React-999-61DAFB img.shields.io/badge/React-19-61DAFB")

    def test_display_rule(self):
        assert _display("16.3.8") == "16"
        assert _display("0.142.2") == "0.142"
