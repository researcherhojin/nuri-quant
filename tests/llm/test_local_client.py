"""고정 · 검사형 로컬 모델 클라이언트 (#1957) — 네트워크 없이 가짜 세션으로 잠근다."""

from __future__ import annotations

import copy
import json
import subprocess
from types import SimpleNamespace

import pytest

from nuri.llm import local_client as lc

DIGEST = "d" * 64


@pytest.fixture
def cfg(tmp_path):
    c = copy.deepcopy(lc.load_config())
    c["expected"] = {"version": "9.9.9", "digest": DIGEST}
    c["archive_dir"] = str(tmp_path / "archive")
    c["canary"]["scored_sha256"] = None
    return c


@pytest.fixture(autouse=True)
def _no_host_commands(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="", returncode=0))


def ok_response(**over):
    r = {
        "model": "m",
        "created_at": "2026-01-01T00:00:00Z",
        "response": "fine",
        "done": True,
        "done_reason": "stop",
        "total_duration": 5,
        "load_duration": 4,
        "prompt_eval_count": 10,  # "hi" 의 바이트 상한(2 + 16) 안
        "prompt_eval_cached_count": 0,
        "prompt_eval_duration": 3,
        "eval_count": 5,
        "eval_duration": 2,
    }
    r.update(over)
    return r


class FakeSession:
    """`/api/version` · `/api/tags` · `/api/generate` 만 흉내 내고 모든 호출을 기록한다."""

    def __init__(self, cfg, *, version="9.9.9", digest=DIGEST, response=None):
        self.cfg, self.version, self.digest = cfg, version, digest
        self.response = response if response is not None else ok_response()
        self.calls: list[tuple[str, str, dict]] = []

    def _r(self, payload):
        return SimpleNamespace(json=lambda: payload, raise_for_status=lambda: None)

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        if url.endswith("/api/version"):
            return self._r({"version": self.version})
        return self._r({"models": [{"name": self.cfg["model"], "digest": self.digest}]})

    def post(self, url, json=None, **kw):  # noqa: A002 — requests 와 같은 이름
        self.calls.append(("POST", url, {"json": json, **kw}))
        if json and "prompt" not in json:
            return self._r({"done_reason": "unload"})
        return self._r(self.response)


class TestBeforeAnyRequest:
    def test_every_pinned_option_is_sent(self, cfg):
        body = lc.build_request("hi", cfg)
        assert set(lc.PINNED_OPTIONS) <= body["options"].keys()
        assert body["keep_alive"] == 0 and body["stream"] is False and body["think"] is False

    @pytest.mark.parametrize("key", lc.PINNED_OPTIONS)
    def test_a_missing_option_is_refused(self, cfg, key):
        """옵션이 빠지면 서버 기본값이 끼어든다 — 기본 context 는 기기마다 다르다."""
        del cfg["options"][key]
        with pytest.raises(lc.LocalModelError) as e:
            lc.build_request("hi", cfg)
        assert e.value.code == "unpinned_options"

    def test_a_prompt_that_could_overflow_is_refused_without_a_request(self, cfg):
        """서버는 넘친 프롬프트의 앞부분을 오류 없이 자른다 — 보내기 전에 막아야 한다."""
        s = FakeSession(cfg)
        cfg["options"]["num_ctx"] = 100
        cfg["options"]["num_predict"] = 10
        with pytest.raises(lc.LocalModelError) as e:
            lc.generate("x" * 80, cfg=cfg, session=s)
        assert e.value.code == "prompt_too_long"
        assert s.calls == []

    def test_the_byte_bound_counts_utf8_bytes_plus_overhead(self, cfg):
        assert lc.byte_bound("가", cfg) == 3 + cfg["template_overhead_tokens"]

    @pytest.mark.parametrize("url", ["http://10.0.0.5:11434", "http://example.com:11434", "http://:11434"])
    def test_a_non_loopback_url_is_refused_without_a_request(self, cfg, url):
        s = FakeSession(cfg)
        cfg["base_url"] = url
        with pytest.raises(lc.LocalModelError) as e:
            lc.generate("hi", cfg=cfg, session=s)
        assert e.value.code == "not_loopback"
        assert s.calls == []

    @pytest.mark.parametrize("url", ["http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434"])
    def test_loopback_urls_pass(self, url):
        assert lc.is_loopback(url)

    def test_the_session_ignores_environment_proxies(self):
        assert lc._session().trust_env is False


class TestRuntimeGuard:
    @pytest.mark.parametrize("over", [{"version": "9.9.8"}, {"digest": "e" * 64}])
    def test_a_mismatch_is_refused_before_any_generate(self, cfg, over):
        s = FakeSession(cfg, **over)
        with pytest.raises(lc.LocalModelError) as e:
            lc.generate("hi", cfg=cfg, session=s)
        assert e.value.code == "runtime_mismatch"
        assert [c[0] for c in s.calls] == ["GET", "GET"]

    def test_a_missing_model_is_refused(self, cfg):
        s = FakeSession(cfg, digest="")
        with pytest.raises(lc.LocalModelError) as e:
            lc.generate("hi", cfg=cfg, session=s)
        assert e.value.code == "model_missing"

    def test_runtime_records_os_and_documented_env_but_not_the_hostname(self, cfg, monkeypatch):
        seen = []

        def fake_run(args, **k):
            seen.append(args)
            return SimpleNamespace(stdout="v" if args[0] == "sw_vers" else "q8_0", returncode=0)

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(lc.socket, "gethostname", lambda: "box" + "-name")
        rt = lc.read_runtime(cfg, FakeSession(cfg))
        assert rt.os_version == "v" and rt.ollama_env["OLLAMA_KV_CACHE_TYPE"] == "q8_0"
        assert set(rt.ollama_env) == set(lc.OLLAMA_ENV)
        assert len(rt.host) == 12 and "box" not in rt.host

    def test_a_failing_host_command_is_recorded_as_empty(self, cfg, monkeypatch):
        def boom(*a, **k):
            raise OSError("no such command")

        monkeypatch.setattr(subprocess, "run", boom)
        assert lc.read_runtime(cfg, FakeSession(cfg)).os_version == ""


class TestColdCallAndChecks:
    def test_the_model_is_unloaded_before_the_call_and_both_skip_proxies_and_redirects(self, cfg):
        s = FakeSession(cfg)
        lc.generate("hi", cfg=cfg, session=s)
        posts = [c for c in s.calls if c[0] == "POST"]
        assert posts[0][2]["json"] == {"model": cfg["model"], "keep_alive": 0}
        assert posts[1][2]["json"]["prompt"] == "hi"
        assert all(c[2]["allow_redirects"] is False for c in s.calls)

    @pytest.mark.parametrize(
        ("over", "failure"),
        [
            ({"prompt_eval_cached_count": None}, "cache_count_missing"),
            ({"prompt_eval_cached_count": 7}, "warm_cache:7"),
            ({"done_reason": "length"}, "done_reason:length"),
            ({"prompt_eval_count": None}, "token_counts_missing"),
            ({"prompt_eval_count": 40000, "eval_count": 1}, "context_exceeded:40001>32768"),
            ({"prompt_eval_count": 500}, "byte_bound_violated:500>18"),
        ],
    )
    def test_each_post_call_violation_fails_the_call_and_is_archived(self, cfg, over, failure):
        resp = ok_response(**over)
        if over.get("prompt_eval_cached_count", 0) is None:
            del resp["prompt_eval_cached_count"]
        with pytest.raises(lc.LocalModelError) as e:
            lc.generate("hi", cfg=cfg, session=FakeSession(cfg, response=resp))
        assert e.value.code == "check_failed"
        assert failure in e.value.detail
        assert e.value.record is not None
        saved = json.loads(open(e.value.record["archive_path"]).read())
        assert failure in saved["failures"]

    def test_length_is_accepted_only_when_asked(self, cfg):
        s = FakeSession(cfg, response=ok_response(done_reason="length"))
        assert lc.generate("hi", cfg=cfg, session=s, allow_length=True)["failures"] == []

    def test_a_schema_is_sent_as_format(self, cfg):
        s = FakeSession(cfg)
        lc.generate("hi", cfg=cfg, session=s, schema={"type": "object"}, archive=False)
        assert s.calls[-1][2]["json"]["format"] == {"type": "object"}


class TestContentHash:
    def test_timing_and_wall_clock_do_not_change_the_hash(self, cfg):
        a = lc.generate("hi", cfg=cfg, session=FakeSession(cfg), archive=False)
        b = lc.generate(
            "hi",
            cfg=cfg,
            session=FakeSession(cfg, response=ok_response(total_duration=99, load_duration=98, created_at="x")),
            archive=False,
        )
        assert a["content_hash"] == b["content_hash"]

    def test_the_output_text_changes_the_hash(self, cfg):
        a = lc.generate("hi", cfg=cfg, session=FakeSession(cfg), archive=False)
        b = lc.generate("hi", cfg=cfg, session=FakeSession(cfg, response=ok_response(response="other")), archive=False)
        assert a["content_hash"] != b["content_hash"]


class TestCanary:
    def test_an_unregistered_canary_refuses_the_batch(self, cfg):
        s = FakeSession(cfg)
        with pytest.raises(lc.LocalModelError) as e:
            lc.check_canary(cfg, session=s)
        assert e.value.code == "canary_unregistered"
        assert s.calls == []

    def test_a_different_output_refuses_and_the_registered_one_passes(self, cfg):
        got = lc.run_canary(cfg, session=FakeSession(cfg))
        cfg["canary"]["scored_sha256"] = "0" * 64
        with pytest.raises(lc.LocalModelError) as e:
            lc.check_canary(cfg, session=FakeSession(cfg))
        assert e.value.code == "canary_mismatch"
        cfg["canary"]["scored_sha256"] = got
        assert lc.check_canary(cfg, session=FakeSession(cfg)) == got


class TestCli:
    def test_runtime_match_and_mismatch(self, cfg, monkeypatch, capsys):
        monkeypatch.setattr(lc, "load_config", lambda: cfg)
        monkeypatch.setattr(lc, "_session", lambda: FakeSession(cfg))
        assert lc.main(["--runtime"]) == 0
        assert "runtime: matches" in capsys.readouterr().out
        monkeypatch.setattr(lc, "_session", lambda: FakeSession(cfg, version="0.0.1"))
        assert lc.main(["--runtime"]) == 2

    def test_canary_and_prompt_file(self, cfg, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(lc, "load_config", lambda: cfg)
        monkeypatch.setattr(lc, "_session", lambda: FakeSession(cfg))
        assert lc.main(["--canary"]) == 0
        p = tmp_path / "p.txt"
        p.write_text("hi")
        assert lc.main(["--prompt-file", str(p)]) == 0
        assert "content_hash" in capsys.readouterr().out
