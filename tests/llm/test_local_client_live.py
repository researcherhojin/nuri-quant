"""실서버 검증 (#1957) — 로컬 Ollama 가 등록 런타임과 같을 때만 돈다.

`pytest -m integration tests/llm/test_local_client_live.py -s` 로 실행한다(기본 실행 · CI 제외).
공식 문서에 없는 동작(넘친 프롬프트의 무음 절단, 토큰 ≤ 바이트 가정)을 이 기기에서 다시 잰다.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import requests

from nuri.llm import local_client as lc

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def cfg():
    c = lc.load_config()
    try:
        lc.check_runtime(lc.read_runtime(c, lc._session()), c)
    except (requests.RequestException, lc.LocalModelError) as e:
        pytest.skip(f"local model server not available as registered: {e}")
    return c


@pytest.fixture
def tcfg(cfg, tmp_path):
    c = copy.deepcopy(cfg)
    c["archive_dir"] = str(tmp_path)
    return c


def _english() -> str:
    return (REPO / "docs" / "STRATEGY.md").read_text()


class SpySession:
    def __init__(self):
        self.inner, self.calls = lc._session(), 0

    def get(self, *a, **k):
        self.calls += 1
        return self.inner.get(*a, **k)

    def post(self, *a, **k):
        self.calls += 1
        return self.inner.post(*a, **k)


def test_the_server_silently_cuts_the_head_and_the_client_refuses_first(tcfg):
    head, tail = "HEAD-MARKER-ALPHA", "TAIL-MARKER-OMEGA"
    prompt = f"{head}\n{_english()[:30000]}\n{tail}\nList every line above that contains MARKER, verbatim."
    s = lc._session()
    s.post(tcfg["base_url"] + "/api/generate", json={"model": tcfg["model"], "keep_alive": 0}, timeout=60)
    raw = s.post(
        tcfg["base_url"] + "/api/generate",
        json={
            "model": tcfg["model"],
            "prompt": prompt,
            "stream": False,
            "think": False,
            "keep_alive": 0,
            "options": {**tcfg["options"], "num_ctx": 4096, "num_predict": 60},
        },
        timeout=tcfg["timeout_s"],
    ).json()
    print(f"\nraw: prompt_eval_count={raw['prompt_eval_count']} done_reason={raw['done_reason']}")
    assert raw["done_reason"] == "stop"  # 서버는 실패로 알리지 않는다
    assert raw["prompt_eval_count"] < 4096 < len(prompt.encode()) // 4
    assert head not in raw["response"] and tail in raw["response"]

    small = copy.deepcopy(tcfg)
    small["options"]["num_ctx"] = 4096
    spy = SpySession()
    with pytest.raises(lc.LocalModelError) as e:
        lc.generate(prompt, cfg=small, session=spy)
    assert e.value.code == "prompt_too_long"
    assert spy.calls == 0


def _digits() -> str:
    return json.dumps([{"id": f"prices:{i}", "close": round(i * 7.919, 3), "volume": i * 104729} for i in range(400)])


@pytest.mark.parametrize(
    ("label", "make"),
    [
        ("numeric JSON", _digits),
        ("Korean", lambda: (REPO / "docs" / "ko" / "STRATEGY.md").read_text()[:20000]),
        ("English", lambda: _english()[:20000]),
    ],
)
def test_prompt_tokens_never_exceed_the_byte_bound(tcfg, label, make):
    text = make()
    rec = lc.generate(text, cfg=tcfg, num_predict=1, allow_length=True)
    n, bound = rec["response"]["prompt_eval_count"], rec["byte_bound"]
    print(f"\n{label}: tokens={n} bound={bound} ratio={n / len(text.encode()):.3f}")
    assert n <= bound


def test_two_cold_calls_give_the_same_content_hash_and_report_load_time(tcfg):
    prompt = "List three risks of long-duration bonds in one sentence each."
    a = lc.generate(prompt, cfg=tcfg)
    b = lc.generate(prompt, cfg=tcfg)
    print(f"\nload_duration_s={a['response']['load_duration'] / 1e9:.2f} / {b['response']['load_duration'] / 1e9:.2f}")
    assert a["content_hash"] == b["content_hash"]
    assert a["response"]["prompt_eval_cached_count"] == 0
