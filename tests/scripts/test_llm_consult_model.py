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
