"""Codex 리뷰 모델은 스크립트가 명시한다 — 머신 설정을 따르지 않는다.

예전 `consult_codex` 는 `-m` 없이 `codex exec` 를 불러 `~/.codex/config.toml` 기본 모델로
돌았고, 아카이브 머리말은 "gpt-5.4" 고정 문자열이라 실제 모델과 달랐다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPT_DIR = Path(__file__).parent.parent.parent / "scripts" / "dev"
sys.path.insert(0, str(SCRIPT_DIR))

spec = importlib.util.spec_from_file_location("llm_consult", SCRIPT_DIR / "llm_consult.py")
assert spec is not None and spec.loader is not None
llm_consult = importlib.util.module_from_spec(spec)
spec.loader.exec_module(llm_consult)


class TestCodexModelIsPinned:
    def test_codex_exec_receives_the_model_flag(self):
        proc = MagicMock(returncode=0, stdout="x\ncodex\nPASS", stderr="")
        with patch.object(llm_consult.subprocess, "run", return_value=proc) as run:
            llm_consult.consult_codex("prompt")
        argv = run.call_args.args[0]
        assert argv[argv.index("-m") + 1] == llm_consult.CODEX_MODEL

    def test_archive_header_names_the_model_that_ran(self):
        md = llm_consult.render_markdown("slug", "p", {"ok": True, "verdict": "PASS"}, None)
        assert f"## Codex ({llm_consult.CODEX_MODEL})" in md


def _load_consult(monkeypatch, **env):
    import os

    for key in list(os.environ):
        if key.startswith(("NURI_LLM_LOCAL_", "NURI_LLM_QWEN_")):
            monkeypatch.delenv(key)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_sends_the_strata_model(monkeypatch):
    module = _load_consult(monkeypatch)
    response = MagicMock(status_code=200)
    response.json.return_value = {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]}
    with patch.object(module.requests, "post", return_value=response) as post:
        assert module.consult_qwen("synthetic")["ok"]
    assert post.call_args.args == ("http://127.0.0.1:8081/v1/chat/completions",)
    assert post.call_args.kwargs["json"]["model"] == "qwen3.8-flash-next-unsloth-ud-q4_k_xl"
    response.raise_for_status.assert_called_once()


def test_existing_defaults_and_explicit_overrides(monkeypatch):
    # 기본은 Strata (2026-10-26) — LM Studio backend 는 제거됐다
    default = _load_consult(monkeypatch)
    assert default.LOCAL_URL == "http://127.0.0.1:8081/v1/chat/completions"
    assert default.LOCAL_MODEL == "qwen3.8-flash-next-unsloth-ud-q4_k_xl"
    assert not hasattr(default, "LOCAL_BACKEND")
    legacy = _load_consult(
        monkeypatch, NURI_LLM_QWEN_URL="http://localhost:9000/v1/chat/completions", NURI_LLM_QWEN_MODEL="legacy"
    )
    assert legacy.LOCAL_MODEL == "legacy"
    assert legacy.LOCAL_URL == "http://localhost:9000/v1/chat/completions"
    override = _load_consult(
        monkeypatch,
        NURI_LLM_LOCAL_MODEL="custom",
        NURI_LLM_QWEN_MODEL="legacy",
        NURI_LLM_LOCAL_URL="http://localhost:8082/v1/chat/completions",
    )
    assert override.LOCAL_MODEL == "custom"
    assert override.LOCAL_URL == "http://localhost:8082/v1/chat/completions"


def test_incomplete_verdicts_are_not_successful():
    for content, finish in [
        ("partial", "length"),
        ("", "stop"),
        ("<think>reason only</think>", "stop"),
        ("text", None),
    ]:
        response = MagicMock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": content}, "finish_reason": finish}]}
        with patch.object(llm_consult.requests, "post", return_value=response):
            assert not llm_consult.consult_qwen("synthetic")["ok"]


def test_http_failure_is_not_parsed_as_a_verdict():
    import pytest
    import requests

    response = MagicMock()
    response.raise_for_status.side_effect = requests.HTTPError("server unavailable")
    with patch.object(llm_consult.requests, "post", return_value=response), pytest.raises(requests.HTTPError):
        llm_consult.consult_qwen("synthetic")
    response.json.assert_not_called()


def test_cli_reports_failure_and_archives_result(tmp_path, monkeypatch):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("synthetic")
    monkeypatch.setattr(
        sys,
        "argv",
        ["consult", "--qwen-only", "--slug", "smoke", "--prompt-file", str(prompt), "--out-dir", str(tmp_path)],
    )
    with (
        patch.object(llm_consult, "consult_qwen", side_effect=ConnectionError("offline")),
        patch.object(llm_consult, "consult_codex") as external,
    ):
        assert llm_consult.main() == 1
    external.assert_not_called()
    assert "**ok:** False" in next(tmp_path.glob("*.md")).read_text()
