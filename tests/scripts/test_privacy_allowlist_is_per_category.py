"""면제는 파일 전체가 아니라 카테고리 단위 (#981).

두 방어선이 **독립적으로** 뚫려 있었다:
  1. `ALLOWLIST_PATHS` 가 `startswith` 로 **파일 전체**를 껐다. `docs/STRATEGY.md` 는
     "패턴 이름을 적을 수도 있어서" 500줄 통째로 빠졌는데, 실제로 451행에 증권사명과
     연금 보유가 숨어 있었다. `test_held_add_mode.py` 는 사유가 "다계좌 NVDA/MSFT"
     인데 정작 가려진 건 픽스처 9곳의 증권사명이었다 — **사유와 실제가 달랐다.**
  2. `BROKER_NAMES_KO` 가 15개뿐이라 #980 에서 잡힌 증권사가 목록에 없었다.

한쪽만 고치면 다른 쪽이 통과시킨다. 그래서 둘 다 잠근다.

⚠️ 증권사명은 **런타임 조립**한다 — 리터럴로 적으면 이 파일을 저장하는 순간
PreToolUse 훅과 CI privacy-scan 이 이 테스트 자체를 차단한다 (`tests/CLAUDE.md`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify.check_privacy_leak import (
    ALL_CATEGORIES,
    ALLOWLIST,
    BROKER_NAMES_KO,
    is_allowlisted,
    line_allows,
    scan_text_for_brokers,
)

ROOT = Path(__file__).resolve().parents[2]


class TestExemptionIsNarrow:
    def test_held_add_mode_exempts_ticker_pnl_but_not_broker_names(self):
        """예전에 증권사명 9곳이 새 나간 바로 그 경로."""
        p = ROOT / "tests/trading/recommend/test_held_add_mode.py"
        assert is_allowlisted(p, "ticker_pnl") is True, "사유에 적힌 면제는 유지돼야 한다"
        assert is_allowlisted(p, "broker_name") is False, (
            "사유는 다계좌 ticker 시나리오인데 증권사명까지 면제되면 사유와 실제가 어긋난다"
        )

    def test_strategy_doc_is_no_longer_wholly_exempt(self):
        """정책 문서 전체 면제가 451행 유출을 숨겼다."""
        assert "docs/STRATEGY.md" not in ALLOWLIST, (
            "문서를 통째로 면제하면 그 안의 실제 유출이 영원히 안 보인다 — "
            "패턴 표 줄만 `privacy-allow` 마커로 면제할 것"
        )

    def test_only_the_scanner_itself_gets_a_blanket_exemption(self):
        """ALL 면제는 세 카테고리를 전부 문서화하는 파일에만."""
        blanket = {k for k, v in ALLOWLIST.items() if v == ALL_CATEGORIES}
        unexpected = {
            k
            for k in blanket
            if not (
                k.startswith((".git", ".venv", ".claude", "node_modules")) or "privacy_leak" in k or "package-lock" in k
            )
        }
        assert not unexpected, f"근거 없는 전면 면제: {sorted(unexpected)}"


class TestInlineMarker:
    def test_marker_scopes_to_the_named_category(self):
        assert line_allows("x  # privacy-allow: broker_name", "broker_name") is True
        assert line_allows("x  # privacy-allow: broker_name", "ticker_pnl") is False

    def test_bare_marker_covers_everything(self):
        assert line_allows("x  <!-- privacy-allow -->", "suspect_numeric") is True

    def test_absent_marker_allows_nothing(self):
        assert line_allows("plain line", "broker_name") is False


class TestBrokerListCoversTheOnesThatSlipped:
    @pytest.mark.parametrize("parts", [("신영", "증권"), ("교보", "증권"), ("현대차", "증권"), ("DB금융", "투자")])
    def test_previously_missing_brokers_are_detected(self, parts):
        name = "".join(parts)
        assert name in BROKER_NAMES_KO, f"{name} 가 목록에 없다 — #980 계열이 다시 통과한다"
        assert scan_text_for_brokers(f"계좌: {name}"), f"{name} 를 탐지하지 못했다"

    def test_kis_stays_deliberately_excluded(self):
        """`한국투자증권` 은 Open API 통합 대상이라 의도적 제외 — 넣으면 정상 코드가 걸린다."""
        kis = "한국" + "투자증권"
        assert kis not in BROKER_NAMES_KO, (
            "KIS 를 넣으면 nuri/collectors/kis_*.py docstring 이 걸린다. "
            "자격증명은 이름이 아니라 config/kis/* 파일 패턴으로 막는다"
        )
