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
        'git -C "repo fixtures" push origin "+HEAD:refs/heads/topic"',
        "git -C . push --force origin topic",
        "git -C . reset --hard HEAD",
        "git -C . clean -fd",
        "git status && git push origin +HEAD:refs/heads/topic",
    ):
        res = evaluate_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": cmd}}}, repo_root=REPO_ROOT)
        assert res["decision"] == "deny", cmd


def test_allows_safe_git_commands():
    for cmd in (
        "git push --force-with-lease origin feat",
        "git clean -nd",
        'git -C "repo fixtures" push --force-with-lease origin HEAD:refs/heads/topic',
        "git -C . status",
    ):
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


def test_blocks_policy_import_variants():
    for content in ("from sqlite3 import connect", "from openai import OpenAI", "import os, sqlite3"):
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {"TargetFile": "nuri/core/db.py", "ReplacementContent": content},
            }
        }
        assert evaluate_hook(payload, repo_root=REPO_ROOT)["decision"] == "deny", content


def test_blocks_protected_env_and_portfolio():
    for rel in (".env", "frontend/.env", "frontend/.env.local", "frontend/.env.new", "config/portfolio.yaml"):
        for tool, path_key in (("view_file", "AbsolutePath"), ("write_to_file", "TargetFile")):
            payload = {"toolCall": {"name": tool, "args": {path_key: str(REPO_ROOT / rel), "CodeContent": "X=1"}}}
            assert evaluate_hook(payload, repo_root=REPO_ROOT)["decision"] == "deny", (tool, rel)


def test_allows_templates_and_gitignored_staged_replacement():
    for rel in (".env.example", "frontend/.env.example", ".env.new"):
        payload = {"toolCall": {"name": "write_to_file", "args": {"TargetFile": rel, "CodeContent": "X=1"}}}
        assert evaluate_hook(payload, repo_root=REPO_ROOT)["decision"] == "allow", rel

    for rel, decision in ((".env.example", "allow"), (".env.new", "deny")):
        payload = {"toolCall": {"name": "view_file", "args": {"AbsolutePath": str(REPO_ROOT / rel)}}}
        assert evaluate_hook(payload, repo_root=REPO_ROOT)["decision"] == decision, rel


def test_staged_replacement_must_be_gitignored(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    payload = {"toolCall": {"name": "write_to_file", "args": {"TargetFile": ".env.new", "CodeContent": "X=1"}}}
    assert evaluate_hook(payload, repo_root=tmp_path)["decision"] == "deny"

    (tmp_path / ".gitignore").write_text(".env.new\n", encoding="utf-8")
    assert evaluate_hook(payload, repo_root=tmp_path)["decision"] == "allow"


def test_checks_requested_and_resolved_protected_paths(tmp_path):
    (tmp_path / ".env.local").symlink_to("note.txt")
    (tmp_path / "alias.txt").symlink_to(".env.secret")
    for path in (".env.local", "alias.txt"):
        payload = {"toolCall": {"name": "view_file", "args": {"AbsolutePath": str(tmp_path / path)}}}
        assert evaluate_hook(payload, repo_root=tmp_path)["decision"] == "deny", path


def test_denies_private_content_without_echoing_it():
    content = "/".join(("", "Users", "sample_account", "notes.txt"))
    res = evaluate_hook(
        {"toolCall": {"name": "write_to_file", "args": {"TargetFile": "notes.txt", "CodeContent": content}}},
        repo_root=REPO_ROOT,
    )
    assert res == {"decision": "deny", "reason": "Privacy leak detected (STRATEGY §4.4.1)."}


def test_allows_the_scanner_to_document_its_own_patterns():
    scanner = "scripts/verify/check_privacy_leak.py"
    content = (REPO_ROOT / scanner).read_text(encoding="utf-8")
    for path, decision in ((scanner, "allow"), (f"{scanner}.txt", "deny")):
        payload = {"toolCall": {"name": "write_to_file", "args": {"TargetFile": path, "CodeContent": content}}}
        assert evaluate_hook(payload, repo_root=REPO_ROOT)["decision"] == decision, path


def test_cli_entrypoint_reads_stdin():
    config = json.loads((REPO_ROOT / ".agents/hooks.json").read_text(encoding="utf-8"))
    entry = config["nuri-invariants"]["PreToolUse"][0]
    for name, args in (
        ("run_command", {"CommandLine": "git clean -fd"}),
        ("view_file", {"AbsolutePath": str(REPO_ROOT / "frontend/.env")}),
    ):
        assert name in entry["matcher"].split("|")
        proc = subprocess.run(
            ["sh", "-c", entry["hooks"][0]["command"]],
            input=json.dumps({"toolCall": {"name": name, "args": args}}),
            text=True,
            capture_output=True,
            cwd=REPO_ROOT / "scripts",
            check=True,
        )
        assert json.loads(proc.stdout)["decision"] == "deny", name
