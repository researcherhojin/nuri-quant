"""`llm_consult --local-only` — 비공개 맥락은 loopback 로컬 모델에만 간다 (STRATEGY §4.4).

`--qwen-only` 만으로는 부족했다: 로컬 URL 은 `NURI_LLM_LOCAL_URL` 로 바꿀 수 있어서
env 하나로 보유 종목이 담긴 prompt 가 다른 머신으로 나간다. `--local-only` 는 URL 의
host 가 loopback 이 아니면 **네트워크를 건드리기 전에** 거부한다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestLocalRequestIgnoresEnvProxy:
    """requests 는 loopback 요청도 HTTP_PROXY / ALL_PROXY 로 보낸다 (2026-10-26 실측).

    전송 직전(adapter)에서 실제로 쓰일 proxies 를 본다 — `requests.post` 를 통째로 바꾸면
    환경 병합이 일어나지 않아 이 결함이 안 보인다.
    """

    @staticmethod
    def _proxies_seen(monkeypatch: pytest.MonkeyPatch, *, trust_env: bool) -> dict:
        import requests
        import requests.adapters

        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            monkeypatch.setenv(key, "http://proxy.example:3128")
        monkeypatch.setenv("ALL_PROXY", "socks5://proxy.example:1080")
        for key in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setattr(llm_consult, "LOCAL_URL", "http://127.0.0.1:1234/v1/chat/completions")
        seen: dict = {}

        def _send(_self, _request, **kwargs):
            seen.update(kwargs.get("proxies") or {})
            resp = requests.Response()
            resp.status_code = 200
            resp._content = b'{"choices":[{"message":{"content":"OK"},"finish_reason":"stop"}]}'
            return resp

        monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _send)
        assert llm_consult.consult_qwen("synthetic", trust_env=trust_env)["ok"]
        return seen

    def test_local_only_request_goes_direct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._proxies_seen(monkeypatch, trust_env=False) == {}

    def test_default_request_still_follows_env_proxy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 대조군 — 이게 비어 있으면 위 테스트는 아무것도 증명하지 않는다
        assert self._proxies_seen(monkeypatch, trust_env=True)


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
        assert local.call_args.kwargs["trust_env"] is False, "--local-only 는 환경 프록시를 끈다"
        external.assert_not_called()
        assert "## Codex" not in next(tmp_path.glob("*_s.md")).read_text(encoding="utf-8")

    @pytest.mark.parametrize("other", ["--codex-only", "--qwen-only"])
    def test_codex_only_cannot_be_combined(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, other: str) -> None:
        flags = ("--local-only", "--codex-only") if other == "--codex-only" else ("--codex-only", "--qwen-only")
        monkeypatch.setattr(sys, "argv", _argv(tmp_path, *flags))
        with pytest.raises(SystemExit) as exc:
            llm_consult.main()
        assert exc.value.code == 2


class TestStrataOnDemand:
    """Strata 는 필요할 때만 켜고, 이 호출이 켰으면 끝나고 끈다 (88GB 상주 — 2026-10-26 소유자 요청)."""

    @pytest.fixture
    def rig(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        fake_bin = tmp_path / "strata"
        fake_bin.write_text("#!/bin/sh\n")
        calls: list[list[str]] = []
        state = {"up": False}

        def _run(argv, **kw):
            calls.append(argv)
            if argv[1:] == ["start", "quiet"]:
                state["up"] = True
            if argv[1:] == ["stop"]:
                state["up"] = False
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(llm_consult, "STRATA_BIN", str(fake_bin))
        monkeypatch.setattr(llm_consult, "LOCAL_URL", llm_consult.STRATA_URL)
        monkeypatch.setattr(llm_consult.subprocess, "run", _run)
        monkeypatch.setattr(llm_consult, "local_server_up", lambda: state["up"])
        monkeypatch.setattr(llm_consult.time, "sleep", lambda s: None)
        return calls, state, fake_bin

    def test_starts_when_down_and_reports_it(self, rig) -> None:
        calls, state, _ = rig
        assert llm_consult.ensure_strata() is True
        assert calls == [[llm_consult.STRATA_BIN, "start", "quiet"]]
        assert state["up"]

    def test_leaves_a_running_server_alone(self, rig) -> None:
        calls, state, _ = rig
        state["up"] = True
        assert llm_consult.ensure_strata() is False
        assert calls == []

    def test_does_not_touch_strata_for_another_local_server(self, rig, monkeypatch: pytest.MonkeyPatch) -> None:
        calls, _, _ = rig
        monkeypatch.setattr(llm_consult, "LOCAL_URL", "http://127.0.0.1:11434/v1/chat/completions")
        assert llm_consult.ensure_strata() is False
        assert calls == []

    def test_without_strata_installed_nothing_happens(self, rig) -> None:
        calls, _, fake_bin = rig
        fake_bin.unlink()
        assert llm_consult.ensure_strata() is False
        assert calls == []

    def test_still_stops_when_the_server_never_comes_up(self, rig, monkeypatch: pytest.MonkeyPatch) -> None:
        """켜기를 시도했으면 끝나고 끈다 — 반쯤 뜬 서버를 남기지 않는다."""
        calls, _, _ = rig
        monkeypatch.setattr(llm_consult, "local_server_up", lambda: False)
        monkeypatch.setattr(llm_consult, "STRATA_START_TIMEOUT_S", 0)
        assert llm_consult.ensure_strata() is True

    @pytest.mark.parametrize("consult_ok", [True, False])
    def test_main_stops_only_what_it_started(self, rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, consult_ok):
        calls, state, _ = rig
        monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--local-only"))
        result = {
            "ok": consult_ok,
            "verdict": "V",
            "reasoning": "",
            "finish_reason": "stop",
            "tokens_in": 1,
            "tokens_out": 1,
        }
        with patch.object(llm_consult, "consult_qwen", return_value=result):
            assert llm_consult.main() == (0 if consult_ok else 1)
        assert [c[1:] for c in calls] == [["start", "quiet"], ["stop"]]
        assert not state["up"], "원래 꺼져 있었으니 끝나면 꺼져 있어야 한다"

    def test_main_does_not_stop_a_server_it_found_running(self, rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        calls, state, _ = rig
        state["up"] = True
        monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--local-only"))
        ok = {"ok": True, "verdict": "V", "reasoning": "", "finish_reason": "stop", "tokens_in": 1, "tokens_out": 1}
        with patch.object(llm_consult, "consult_qwen", return_value=ok):
            assert llm_consult.main() == 0
        assert calls == []
        assert state["up"]

    def test_main_stops_even_if_archiving_raises(self, rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        calls, _, _ = rig
        monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--local-only"))
        with (
            patch.object(llm_consult, "consult_qwen", return_value={"ok": True}),
            patch.object(llm_consult, "render_markdown", side_effect=RuntimeError("disk")),
            pytest.raises(RuntimeError),
        ):
            llm_consult.main()
        assert calls[-1][1:] == ["stop"]


class TestLocalServerUp:
    def test_probe_ignores_env_proxies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import requests
        import requests.adapters

        monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:3128")
        monkeypatch.setattr(llm_consult, "LOCAL_URL", llm_consult.STRATA_URL)
        seen: dict = {}

        def _send(_self, request, **kwargs):
            seen["url"] = request.url
            seen["proxies"] = kwargs.get("proxies") or {}
            resp = requests.Response()
            resp.status_code = 200
            return resp

        monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _send)
        assert llm_consult.local_server_up()
        assert seen == {"url": "http://127.0.0.1:8081/v1/models", "proxies": {}}

    def test_connection_error_is_down(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import requests
        import requests.adapters

        def _send(*a, **kw):
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _send)
        assert llm_consult.local_server_up() is False
