"""`.env.example` 이 dotenv 로 의도대로 파싱되는지 (#902 후속, 2026-07-28 발견).

`KEY=<공백들>  # 설명` 형태를 python-dotenv 는 **주석을 값으로** 읽는다. 미설정을
뜻하려던 19개 키가 전부 `"# ..."` 문자열 값을 갖게 됐고, 프로덕션 `.env` 가 이
템플릿에서 복사돼 `FRED_API_KEY` 가 36자 주석 문자열이 됐다. FRED 호출이 api_key
자리에 주석을 실어 400 을 받았지만, 코드가 graceful fallback 이라 **아무도 몰랐다**.

같은 형태가 Discord webhook 12개·KIS 계좌 2개·API 키 3개에 있었다. webhook URL 이
주석 문자열이면 발송이 조용히 실패하고, 계좌번호가 주석이면 조회가 실패한다.

주석은 키 **위 줄**에 둔다. 그러면 값이 빈 문자열로 파싱된다.
"""

from __future__ import annotations

import re
from pathlib import Path

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / ".env.example"


class TestEnvExampleParsing:
    def test_no_value_is_actually_a_comment(self):
        """어떤 키도 `#` 로 시작하는 값을 갖지 않는다.

        Gotcha-Test Pair: `KEY=  # 설명` 형태로 되돌리면 그 키가 여기 잡힌다.
        """
        values = dotenv_values(ENV_EXAMPLE)
        polluted = {k: v for k, v in values.items() if v and v.lstrip().startswith("#")}
        assert polluted == {}, "주석이 값으로 파싱된 키 — 주석을 키 위 줄로 옮길 것:\n" + "\n".join(
            f"  {k} = {v[:60]!r}" for k, v in polluted.items()
        )

    def test_no_inline_comment_after_assignment(self):
        """소스 레벨에서도 `KEY=<공백># ...` 패턴이 없다.

        위 파싱 테스트는 dotenv 동작에 의존한다. dotenv 가 언젠가 인라인 주석을
        스트립하게 바뀌어도 이 형태는 헷갈리므로 소스 형태 자체를 금지한다.
        """
        pattern = re.compile(r"^([A-Z_][A-Z0-9_]*)=[ \t]+#")
        offenders = [
            f"{i}: {line}"
            for i, line in enumerate(ENV_EXAMPLE.read_text(encoding="utf-8").split("\n"), 1)
            if pattern.match(line)
        ]
        assert offenders == [], "인라인 주석 발견 (주석은 키 위 줄로):\n" + "\n".join(offenders)

    def test_placeholder_keys_parse_as_empty(self):
        """미설정 의도인 키는 빈 문자열로 파싱된다 — falsy 여야 코드의 fallback 이 돈다."""
        values = dotenv_values(ENV_EXAMPLE)
        # 코드가 `if not X:` 로 폴백을 결정하는 대표 키들
        for key in ("FRED_API_KEY", "DISCORD_WEBHOOK_BRIEF", "LLAMA_MODEL_PATH"):
            if key in values:
                assert not values[key], f"{key} 는 미설정(falsy)이어야 폴백 경로가 동작한다"
