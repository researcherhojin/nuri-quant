"""모듈 수준 `publish()` 의 싱글턴 재사용 — 한 프로세스에서 publisher 는 한 번만 만든다.

기존 두 테스트(`test_module_publish_singleton` · `test_module_publish_accepts_string`)는 각자 한 번씩만
부르므로, 두 번째 호출이 기존 인스턴스를 타는지는 xdist·shard 배치가 우연히 둘을 같은 워커에 놓을 때만
실행됐다 — Codecov 의 publisher.py:348 부분 분기가 실행마다 달라진 이유다. 여기서는 시작 상태를 비우고
한 테스트 안에서 두 번 부른다.
"""

from __future__ import annotations

from nuri.agents.discord import publisher as pub
from nuri.agents.discord.publisher import Channel


def test_the_module_publisher_is_built_once_and_reused(monkeypatch):
    built: list[object] = []
    sent: list[tuple] = []

    class _FakePublisher:
        def __init__(self):
            built.append(self)

        def publish_text(self, channel, content, actor_name=None, run_id=None, decision_id=None):
            sent.append((self, channel, content))
            return "ok"

    monkeypatch.setattr(pub, "_singleton", None)  # 이전 테스트가 남긴 인스턴스와 무관하게 시작
    monkeypatch.setattr(pub, "DiscordPublisher", _FakePublisher)

    assert pub.publish(Channel.OPS, "first") == "ok"
    assert pub.publish("brief", "second") == "ok"

    assert len(built) == 1
    assert [(s[0] is built[0], s[1], s[2]) for s in sent] == [
        (True, Channel.OPS, "first"),
        (True, Channel.BRIEF, "second"),
    ]
