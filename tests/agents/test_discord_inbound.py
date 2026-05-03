"""DiscordInboundListener tests (#582 E1).

검증:
- _channel_targets() env 변환 (정상/누락/non-numeric)
- mask_placeholder() 통화 literal redaction (USD / KRW)
- emit_message() 정상 path / off-channel skip / bot author skip / file payload shape
- emit_reaction() 정상 path / off-channel skip
- attach() env 미설정 시 False, 설정 시 3 events 등록

discord.py 의 Message / RawReactionActionEvent 자체는 무겁고 cache-bound 라
duck-typed MagicMock 으로 대체 — 본 모듈은 channel.id / author / content / emoji 등
attribute 만 사용하므로 충분.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from nuri.agents.discord import inbound


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """inbound 출력 디렉토리를 tmp_path 로 redirect + env 깨끗이 시작."""
    monkeypatch.setenv("NURI_DISCORD_INBOUND_DIR", str(tmp_path))
    monkeypatch.delenv("DISCORD_CHANNEL_AGENT_CONTROL_ID", raising=False)
    monkeypatch.delenv("DISCORD_CHANNEL_AGENT_DEV_LOG_ID", raising=False)
    return tmp_path


def _mock_message(
    channel_id: int,
    content: str = "hello",
    *,
    bot_author: bool = False,
    msg_id: int = 1,
    parent_id: int | None = None,
):
    msg = MagicMock()
    msg.channel.id = channel_id
    # parent_id=None 이면 channel 이 일반 TextChannel — 기본 MagicMock 의 parent_id
    # 가 truthy 이라 명시 None set 필요.
    msg.channel.parent_id = parent_id
    msg.author.bot = bot_author
    msg.author.id = 9999
    msg.author.display_name = "tester"
    msg.id = msg_id
    msg.content = content
    return msg


def _mock_reaction(channel_id: int, user_id: int = 9999, msg_id: int = 1, emoji: str = "✅"):
    payload = MagicMock()
    payload.channel_id = channel_id
    payload.user_id = user_id
    payload.message_id = msg_id
    payload.emoji = emoji
    return payload


class TestChannelTargets:
    def test_returns_empty_when_env_unset(self, sandbox):
        assert inbound._channel_targets() == {}

    def test_reads_both_channels(self, sandbox, monkeypatch):
        monkeypatch.setenv("DISCORD_CHANNEL_AGENT_CONTROL_ID", "111")
        monkeypatch.setenv("DISCORD_CHANNEL_AGENT_DEV_LOG_ID", "222")
        targets = inbound._channel_targets()
        assert targets == {111: "agent-control", 222: "agent-dev-log"}

    def test_skips_non_numeric(self, sandbox, monkeypatch):
        monkeypatch.setenv("DISCORD_CHANNEL_AGENT_CONTROL_ID", "garbage")
        monkeypatch.setenv("DISCORD_CHANNEL_AGENT_DEV_LOG_ID", "333")
        assert inbound._channel_targets() == {333: "agent-dev-log"}

    def test_skips_blank(self, sandbox, monkeypatch):
        monkeypatch.setenv("DISCORD_CHANNEL_AGENT_CONTROL_ID", "  ")
        assert inbound._channel_targets() == {}


class TestMaskPlaceholder:
    def test_redacts_dollar_amount(self):
        assert "[REDACTED]" in inbound.mask_placeholder("buy $1.5M of stock")

    def test_redacts_won_amount(self):
        # 1,000,000 같은 콤마 포함 형식도 handle.
        assert "[REDACTED]" in inbound.mask_placeholder("총 ₩1,000,000 보유")

    def test_preserves_non_monetary(self):
        text = "ticker NVDA 검토 부탁"
        assert inbound.mask_placeholder(text) == text

    def test_handles_empty_and_none(self):
        assert inbound.mask_placeholder("") == ""
        assert inbound.mask_placeholder(None) == ""  # type: ignore[arg-type]


class TestEmitMessage:
    def test_writes_file_for_target_channel(self, sandbox):
        msg = _mock_message(111, content="loop start")
        path = inbound.emit_message(msg, targets={111: "agent-control"})
        assert path is not None
        assert path.exists()
        body = json.loads(path.read_text())
        assert body["type"] == "message"
        assert body["channel_label"] == "agent-control"
        assert body["content_masked"] == "loop start"
        assert body["author_name"] == "tester"

    def test_returns_none_for_off_channel(self, sandbox):
        msg = _mock_message(999)
        assert inbound.emit_message(msg, targets={111: "agent-control"}) is None
        # 파일도 안 만들어졌는지.
        assert list(sandbox.iterdir()) == []

    def test_skips_bot_author(self, sandbox):
        msg = _mock_message(111, bot_author=True)
        assert inbound.emit_message(msg, targets={111: "agent-control"}) is None

    def test_masks_monetary_content(self, sandbox):
        msg = _mock_message(111, content="execute $50,000 buy now", msg_id=42)
        path = inbound.emit_message(msg, targets={111: "agent-control"})
        assert path is not None
        body = json.loads(path.read_text())
        assert "[REDACTED]" in body["content_masked"]
        assert "$50,000" not in body["content_masked"]

    def test_falls_back_to_call_time_targets(self, sandbox, monkeypatch):
        """targets 인자 없으면 _channel_targets() 통해 env read."""
        monkeypatch.setenv("DISCORD_CHANNEL_AGENT_CONTROL_ID", "555")
        msg = _mock_message(555)
        path = inbound.emit_message(msg)
        assert path is not None and path.exists()

    def test_thread_message_resolves_via_parent_id(self, sandbox):
        """thread 안의 메시지도 parent channel 매핑으로 처리 (issue 별 thread 운영 대비)."""
        # channel.id = thread ID (env 미매칭) / parent_id = #agent-dev-log channel ID (매칭).
        msg = _mock_message(channel_id=987654, content="thread post", parent_id=222)
        path = inbound.emit_message(msg, targets={222: "agent-dev-log"})
        assert path is not None
        body = json.loads(path.read_text())
        assert body["channel_label"] == "agent-dev-log"
        assert body["channel_id"] == "987654"  # thread ID 보존 (debug 용)

    def test_thread_message_returns_none_for_off_parent(self, sandbox):
        """parent 도 매칭 안 되면 무시 — 다른 채널의 thread 도 default-deny."""
        msg = _mock_message(channel_id=987654, parent_id=999)
        assert inbound.emit_message(msg, targets={222: "agent-dev-log"}) is None


class TestEmitReaction:
    def test_writes_file_for_target_channel(self, sandbox):
        payload = _mock_reaction(222, emoji="✅")
        path = inbound.emit_reaction(payload, "reaction_add", targets={222: "agent-dev-log"})
        assert path is not None
        body = json.loads(path.read_text())
        assert body["type"] == "reaction_add"
        assert body["emoji"] == "✅"
        assert body["channel_label"] == "agent-dev-log"

    def test_returns_none_for_off_channel(self, sandbox):
        payload = _mock_reaction(999)
        assert inbound.emit_reaction(payload, "reaction_add", targets={222: "agent-dev-log"}) is None

    def test_remove_kind_persists(self, sandbox):
        payload = _mock_reaction(222, emoji="❌")
        path = inbound.emit_reaction(payload, "reaction_remove", targets={222: "agent-dev-log"})
        assert path is not None
        body = json.loads(path.read_text())
        assert body["type"] == "reaction_remove"


class TestAttach:
    def test_returns_false_when_env_unset(self, sandbox):
        bot = MagicMock()
        assert inbound.attach(bot) is False
        bot.event.assert_not_called()

    def test_registers_three_events_when_env_set(self, sandbox, monkeypatch):
        monkeypatch.setenv("DISCORD_CHANNEL_AGENT_CONTROL_ID", "111")
        monkeypatch.setenv("DISCORD_CHANNEL_AGENT_DEV_LOG_ID", "222")
        bot = MagicMock()
        # bot.event 는 decorator: 받은 함수를 그대로 반환.
        bot.event.side_effect = lambda f: f
        assert inbound.attach(bot) is True
        # 3 handlers (on_message + on_raw_reaction_add + on_raw_reaction_remove).
        assert bot.event.call_count == 3
        registered = {call.args[0].__name__ for call in bot.event.call_args_list}
        assert registered == {"on_message", "on_raw_reaction_add", "on_raw_reaction_remove"}
