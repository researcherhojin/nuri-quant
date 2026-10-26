"""`llm_consult --local-only` — 비공개 맥락은 loopback 로컬 모델에만 간다 (STRATEGY §4.4).

`--qwen-only` 만으로는 부족했다: 로컬 URL 은 `NURI_LLM_LOCAL_URL` 로 바꿀 수 있어서
env 하나로 보유 종목이 담긴 prompt 가 다른 머신으로 나간다. `--local-only` 는 URL 의
host 가 loopback 이 아니면 **네트워크를 건드리기 전에** 거부한다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).parent.parent.parent / "scripts" / "dev"
spec = importlib.util.spec_from_file_location("llm_consult", SCRIPT_DIR / "llm_consult.py")
assert spec is not None and spec.loader is not None
llm_consult = importlib.util.module_from_spec(spec)
spec.loader.exec_module(llm_consult)


class TestIsLoopbackUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:1234/v1/chat/completions",
            "http://127.8.9.10:8081/v1/chat/completions",
            "http://[::1]:1234/v1/chat/completions",
            "http://localhost:1234/v1/chat/completions",
        ],
    )
    def test_accepts_loopback(self, url: str) -> None:
        assert llm_consult.is_loopback_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1@evil.example/v1",  # userinfo 뒤 진짜 host
            "http://127.0.0.1.evil.example/v1",  # 접두 일치
            "http://localhost.evil.example/v1",
            "http://10.0.0.5:1234/v1/chat/completions",  # LAN 다른 머신
            "https://api.example.com/v1/chat/completions",
            "http://[::1/v1",  # 파싱 실패
            "not a url",
            "",
        ],
    )
    def test_rejects_everything_else(self, url: str) -> None:
        assert not llm_consult.is_loopback_url(url)


def _argv(tmp_path: Path, *flags: str) -> list[str]:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("synthetic private context", encoding="utf-8")
    return ["consult", *flags, "--slug", "s", "--prompt-file", str(prompt), "--out-dir", str(tmp_path)]


class TestLocalOnlyCli:
    def test_non_loopback_url_is_refused_before_any_network(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        # LOCAL_URL 은 import 시점에 정해지므로 모듈 속성을 바꾼다
        monkeypatch.setattr(llm_consult, "LOCAL_URL", "http://10.0.0.5:1234/v1/chat/completions")
        monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--local-only"))
        with (
            patch.object(llm_consult.requests, "post", side_effect=AssertionError("network")) as post,
            patch.object(llm_consult.subprocess, "run", side_effect=AssertionError("codex")) as run,
        ):
            assert llm_consult.main() == 2
        post.assert_not_called()
        run.assert_not_called()
        assert not list(tmp_path.glob("*_s.md")), "거부된 런은 archive 를 남기지 않는다"
        err = capsys.readouterr().err
        assert "refused" in err
        assert "10.0.0.5" not in err, "URL 값은 로그로 새지 않는다"

    def test_loopback_url_runs_the_local_model_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_consult, "LOCAL_URL", "http://127.0.0.1:1234/v1/chat/completions")
        monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--local-only"))
        ok = {"ok": True, "verdict": "V", "reasoning": "", "finish_reason": "stop", "tokens_in": 1, "tokens_out": 1}
        with (
            patch.object(llm_consult, "consult_qwen", return_value=ok) as local,
            patch.object(llm_consult, "consult_codex") as external,
        ):
            assert llm_consult.main() == 0
        local.assert_called_once()
        external.assert_not_called()
        assert "## Codex" not in next(tmp_path.glob("*_s.md")).read_text(encoding="utf-8")

    @pytest.mark.parametrize("other", ["--codex-only", "--qwen-only"])
    def test_codex_only_cannot_be_combined(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, other: str) -> None:
        flags = ("--local-only", "--codex-only") if other == "--codex-only" else ("--codex-only", "--qwen-only")
        monkeypatch.setattr(sys, "argv", _argv(tmp_path, *flags))
        with pytest.raises(SystemExit) as exc:
            llm_consult.main()
        assert exc.value.code == 2
