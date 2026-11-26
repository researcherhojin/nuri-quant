"""Tests for scripts/hooks/agy_pre_tool_guard.py."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.hooks.agy_pre_tool_guard import evaluate_hook

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_blocks_destructive_git_commands():
    for cmd in (
        "git push --force origin main",
        "git push -f origin feat",
        "git reset --hard HEAD~1",
        "git clean -fd",
        "git clean -dfx",
        "git clean -d --force",
    ):
        res = evaluate_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": cmd}}}, repo_root=REPO_ROOT)
        assert res["decision"] == "deny", cmd


def test_allows_safe_git_commands():
    for cmd in ("git push --force-with-lease origin feat", "git clean -nd"):
        res = evaluate_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": cmd}}}, repo_root=REPO_ROOT)
        assert res["decision"] == "allow", cmd


def test_blocks_sqlite3_openai_and_datetime_now_in_nuri():
    assert (
        evaluate_hook(
            {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {"TargetFile": "nuri/core/db.py", "ReplacementContent": "import sqlite3\n"},
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
                    "name": "write_to_file",
                    "args": {"TargetFile": "nuri/llm/other.py", "CodeContent": "import openai\n"},
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
                    "name": "multi_replace_file_content",
                    "args": {
                        "TargetFile": "nuri/core/rules.py",
                        "ReplacementChunks": [{"ReplacementContent": "x = datetime.now()\n"}],
                    },
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
                    "name": "replace_file_content",
                    "args": {"TargetFile": "nuri/core/db/connection.py", "ReplacementContent": "import sqlite3\n"},
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
                    "name": "replace_file_content",
                    "args": {"TargetFile": "nuri/llm/openai_client.py", "ReplacementContent": "import openai\n"},
                }
            },
            repo_root=REPO_ROOT,
        )["decision"]
        == "allow"
    )


def test_blocks_protected_env_and_portfolio():
    for rel in (".env", "config/portfolio.yaml"):
        res = evaluate_hook(
            {"toolCall": {"name": "write_to_file", "args": {"TargetFile": str(REPO_ROOT / rel), "CodeContent": "X=1"}}},
            repo_root=REPO_ROOT,
        )
        assert res["decision"] == "deny", rel


def test_denies_private_content_without_echoing_it():
    content = "/".join(("", "Users", "sample_account", "notes.txt"))
    res = evaluate_hook(
        {"toolCall": {"name": "write_to_file", "args": {"TargetFile": "notes.txt", "CodeContent": content}}},
        repo_root=REPO_ROOT,
    )
    assert res == {"decision": "deny", "reason": "Privacy leak detected (STRATEGY §4.4.1)."}


def test_cli_entrypoint_reads_stdin():
    config = json.loads((REPO_ROOT / ".agents/hooks.json").read_text(encoding="utf-8"))
    hook = config["nuri-invariants"]["PreToolUse"][0]["hooks"][0]
    proc = subprocess.run(
        ["sh", "-c", hook["command"]],
        input=json.dumps({"toolCall": {"name": "run_command", "args": {"CommandLine": "git clean -fd"}}}),
        text=True,
        capture_output=True,
        cwd=REPO_ROOT / "scripts",
        check=True,
    )
    assert json.loads(proc.stdout)["decision"] == "deny"
