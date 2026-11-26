"""Tests for scripts/hooks/agy_pre_tool_guard.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.hooks.agy_pre_tool_guard import evaluate_hook

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_blocks_destructive_git_commands():
    for cmd in (
        "git push --force origin main",
        "git push -f origin feat",
        "git reset --hard HEAD~1",
        "git clean -fd",
    ):
        res = evaluate_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": cmd}}}, repo_root=REPO_ROOT)
        assert res["decision"] == "deny", cmd


def test_allows_safe_git_commands():
    res = evaluate_hook(
        {"toolCall": {"name": "run_command", "args": {"CommandLine": "git push --force-with-lease origin feat"}}},
        repo_root=REPO_ROOT,
    )
    assert res["decision"] == "allow"


def test_blocks_sqlite3_openai_and_datetime_now_in_nuri():
    assert (
        evaluate_hook(
            {
                "toolCall": {
                    "name": "edit_file",
                    "args": {"Path": str(REPO_ROOT / "nuri/api/main.py"), "Replacement": "import sqlite3\n"},
                }
            },
            repo_root=REPO_ROOT,
        )["decision"]
        == "deny"
    )
    assert (
        evaluate_hook(
            {
                "toolCall": {
                    "name": "write_file",
                    "args": {"Path": str(REPO_ROOT / "nuri/llm/other.py"), "Content": "import openai\n"},
                }
            },
            repo_root=REPO_ROOT,
        )["decision"]
        == "deny"
    )
    assert (
        evaluate_hook(
            {
                "toolCall": {
                    "name": "edit_file",
                    "args": {"Path": str(REPO_ROOT / "nuri/core/rules.py"), "Replacement": "x = datetime.now()\n"},
                }
            },
            repo_root=REPO_ROOT,
        )["decision"]
        == "deny"
    )


def test_allows_sole_importers():
    assert (
        evaluate_hook(
            {
                "toolCall": {
                    "name": "edit_file",
                    "args": {"Path": str(REPO_ROOT / "nuri/core/db/connection.py"), "Replacement": "import sqlite3\n"},
                }
            },
            repo_root=REPO_ROOT,
        )["decision"]
        == "allow"
    )
    assert (
        evaluate_hook(
            {
                "toolCall": {
                    "name": "edit_file",
                    "args": {"Path": str(REPO_ROOT / "nuri/llm/openai_client.py"), "Replacement": "import openai\n"},
                }
            },
            repo_root=REPO_ROOT,
        )["decision"]
        == "allow"
    )


def test_blocks_protected_env_and_portfolio():
    for rel in (".env", "config/portfolio.yaml"):
        res = evaluate_hook(
            {"toolCall": {"name": "write_file", "args": {"Path": str(REPO_ROOT / rel), "Content": "X=1"}}},
            repo_root=REPO_ROOT,
        )
        assert res["decision"] == "deny", rel


def test_cli_entrypoint_reads_stdin():
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/hooks/agy_pre_tool_guard.py")],
        input=json.dumps({"toolCall": {"name": "run_command", "args": {"CommandLine": "git status"}}}),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(proc.stdout)["decision"] == "allow"
