"""Antigravity PreToolUse guard mirroring .claude/settings.json invariants."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]

_DESTRUCTIVE_GIT_RE = re.compile(
    r"git\s+push\s+([^\s]+\s+)*(-f|--force)(\s|$)"
    r"|git\s+reset\s+--hard"
    r"|git\s+clean\s+-[a-z]*f[a-z]*(\s|$)",
    re.IGNORECASE,
)


def _deny(reason: str) -> dict[str, str]:
    return {"decision": "deny", "reason": reason}


def _allow() -> dict[str, str]:
    return {"decision": "allow"}


def _is_gitignored(file_path: Path, repo_root: Path) -> bool:
    try:
        res = subprocess.run(
            ["git", "check-ignore", "-q", "--", str(file_path)],
            cwd=str(repo_root),
            check=False,
            capture_output=True,
        )
        return res.returncode == 0
    except OSError:
        return False


def _check_privacy(content: str, repo_root: Path) -> str | None:
    py = repo_root / ".venv/bin/python"
    script = repo_root / "scripts/verify/check_privacy_leak.py"
    if not (py.is_file() and script.is_file()):
        return None
    res = subprocess.run(
        [str(py), str(script), "--message", "--quiet"],
        input=content,
        text=True,
        capture_output=True,
        cwd=str(repo_root),
        check=False,
        timeout=5,
    )
    if res.returncode != 0:
        summary = " ".join((res.stdout + " " + res.stderr).splitlines()[:3]).strip()
        return f"Privacy leak detected (STRATEGY §4.4.1): {summary}"
    return None


def evaluate_hook(payload: dict[str, Any], repo_root: Path = _REPO_ROOT) -> dict[str, str]:
    """Evaluate a PreToolUse payload and return an allow/deny decision."""
    tool_call = payload.get("toolCall") or {}
    name = tool_call.get("name", "")
    args = tool_call.get("args") or {}

    if name == "run_command":
        cmd = str(args.get("CommandLine") or "")
        if _DESTRUCTIVE_GIT_RE.search(cmd):
            return _deny("Destructive git command blocked (force push / hard reset / clean -f).")
        return _allow()

    if name in ("write_file", "edit_file"):
        raw_path = str(args.get("Path") or "")
        if not raw_path:
            return _allow()

        resolved = Path(os.path.realpath(raw_path))
        try:
            rel = resolved.relative_to(Path(os.path.realpath(repo_root)))
        except ValueError:
            return _allow()

        rel_posix = rel.as_posix()

        if (
            rel_posix in (".env", "config/portfolio.yaml")
            or rel_posix.startswith(".env.")
            and rel_posix != ".env.example"
        ):
            return _deny(f"Protected file cannot be modified directly: {rel_posix}")

        content = str(args.get("Content") or args.get("Replacement") or "")
        if not content:
            return _allow()

        if rel_posix.startswith("nuri/") and rel_posix.endswith(".py"):
            if rel_posix not in ("nuri/core/db/connection.py", "nuri/core/db.py") and "import sqlite3" in content:
                return _deny("sqlite3 may only be imported in nuri/core/db/connection.py (AGENTS.md Rule #1).")
            if rel_posix != "nuri/llm/openai_client.py" and "import openai" in content:
                return _deny("openai may only be imported in nuri/llm/openai_client.py (AGENTS.md Rule #6).")
            if rel_posix != "nuri/core/timezone.py" and "datetime.now(" in content:
                return _deny(
                    "Direct datetime.now() is forbidden in nuri/; use kst_now()/today_kst()/utc_now() (Rule #3)."
                )

        if not _is_gitignored(resolved, repo_root):
            leak_reason = _check_privacy(content, repo_root)
            if leak_reason:
                return _deny(leak_reason)

    return _allow()


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print(json.dumps(_allow()))
        return 0
    decision = evaluate_hook(payload)
    print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
