"""stdio 실호출 — 진짜 서버 프로세스를 띄워 MCP 프로토콜로 도구를 부른다 (#1306).

수용 기준 "Claude Code 세션에서 Tier 1 도구 실호출" 의 기계화된 형태다: 클라이언트
SDK 로 initialize → list_tools → call_tool 전 구간을 밟는다. 인프로세스 함수 호출로는
스키마 직렬화·서버 기동·NURI_DB_PATH 주입(모듈 import 시점에 읽힌다)을 못 잠근다.

도구 목록은 **동치**로 잠근다 — 쓰기 도구가 하나라도 생기면 여기서 걸린다
(read-only 수용 기준의 프로토콜 수준 표현).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anyio
import pytest

from nuri.core.db import get_db, init_db

REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TOOLS = {"siege_status", "buy_candidates", "macro_facts"}


@pytest.fixture()
def anyio_backend():
    return "asyncio"


@pytest.fixture()
def seeded_db(tmp_path):
    path = tmp_path / "live.db"
    init_db(path)
    with get_db(path) as conn:
        conn.execute(
            "INSERT INTO certifications (timestamp, certified, score, total_conditions,"
            " passed, failed, warnings, regime, conditions_json, caller)"
            " VALUES ('2026-08-29T09:00:00', 1, 0.9, 10, 9, 1, 0, 'bull_low_vol', '{}', 'premarket_brief')"
        )
        conn.execute(
            "INSERT INTO candidate_runs (run_date, regime, vix, threshold,"
            " n_scored, n_qualified, n_emitted, n_skipped)"
            " VALUES ('2026-08-29', 'bull_low_vol', 15.2, 0.6, 100, 4, 1, 1)"
        )
        run_id = conn.execute("SELECT id FROM candidate_runs").fetchone()[0]
        conn.executemany(
            "INSERT INTO candidate_ledger (run_id, ticker, disposition, reason, score,"
            " entry, stop, tp1, tp2) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (run_id, "AAAA", "emitted", "momentum", 0.9, 100.0, 93.0, 120.0, 140.0),
                (run_id, "HELD", "skipped", "held (보유 중)", 0.7, None, None, None, None),
            ],
        )
        conn.execute("INSERT INTO macro (indicator, date, value, source) VALUES ('vix', '2026-08-29', 15.2, 'cboe')")
    return path


@pytest.mark.anyio
async def test_stdio_live_tool_calls(seeded_db):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "nuri.mcp.server"],
        cwd=str(REPO_ROOT),
        # NURI_DB_PATH 는 connection.py 모듈 import 시점에 읽힌다 — 프로세스 env 로
        # 주입해야 실제 배포 경로(클라이언트가 env 를 물려주는)와 같은 축을 탄다.
        env={**os.environ, "NURI_DB_PATH": str(seeded_db)},
    )

    with anyio.fail_after(30):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                assert names == EXPECTED_TOOLS, (
                    f"도구 집합이 계약과 다르다: {sorted(names)} — 새 도구는 privacy 잠금과 함께 리뷰"
                )

                macro = await session.call_tool("macro_facts", {})
                assert not macro.is_error
                macro_text = "".join(c.text for c in macro.content if hasattr(c, "text"))
                assert "15.2" in macro_text and "bull_low_vol" in macro_text

                cand = await session.call_tool("buy_candidates", {})
                assert not cand.is_error
                cand_text = "".join(c.text for c in cand.content if hasattr(c, "text"))
                assert "AAAA" in cand_text, "emitted 후보가 프로토콜 경계를 못 넘었다"
                assert "HELD" not in cand_text and "보유" not in cand_text, (
                    "보유 신호가 프로토콜 경계를 넘었다 — readmodel 잠금과 서버 배선 사이 어딘가가 샌다"
                )

                siege = await session.call_tool("siege_status", {"limit": 3})
                assert not siege.is_error
                siege_text = "".join(c.text for c in siege.content if hasattr(c, "text"))
                parsed = json.loads(siege_text) if siege_text.strip().startswith("[") else None
                assert "premarket_brief" in siege_text
                if parsed is not None:
                    assert "conditions_json" not in json.dumps(parsed)
