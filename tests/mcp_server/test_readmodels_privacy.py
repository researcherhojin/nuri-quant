"""Tier 1 read model 의 privacy 경계 잠금 (#1306).

핵심은 출력 계약이다 (codex plan 리뷰 7): **정확 스키마 동치** + **시맨틱 유출
케이스**(보유/행동이 배어든 행을 시드하고 응답에 안 나옴을 본다)가 1차 방어이고,
구조 스윕(테이블 allowlist·readonly 강제)은 보조다.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from nuri.core.db import get_db, init_db
from nuri.mcp import readmodels
from nuri.mcp.readmodels import ALLOWED

MCP_DIR = Path(__file__).resolve().parents[2] / "nuri" / "mcp"

#: 이 이름이 응답 어디에든 키로 나타나면 그 자체로 결함이다 — holdings/계좌/행동 축.
FORBIDDEN_KEYS = {
    "quantity",
    "avg_price",
    "shares",
    "account",
    "total_invested",
    "cash_balance",
    "acted",
    "acted_at",
    "reason",
    "disposition",
    "conditions_json",
    "portfolio_hash",
    "pnl_7d",
    "pnl_30d",
    "pnl_60d",
    "pnl_90d",
    "reasoning",
    "agent_verdicts",
    "scoring_detail",
}


@pytest.fixture()
def seeded_db(tmp_path):
    """emitted 2 + (보유/행동이 배어든) skipped 2 를 시드한 격리 DB."""
    path = tmp_path / "t.db"
    init_db(path)
    with get_db(path) as conn:
        conn.execute(
            "INSERT INTO certifications (timestamp, certified, score, total_conditions,"
            " passed, failed, warnings, regime, portfolio_hash, conditions_json, caller)"
            " VALUES ('2026-08-29T09:00:00', 1, 0.9, 10, 9, 1, 0, 'bull_low_vol',"
            " 'deadbeef', '{\"concentration_pct\": 41.2}', 'premarket_brief')"
        )
        conn.execute(
            "INSERT INTO candidate_runs (run_date, regime, vix, threshold, blocked_reason,"
            " n_scored, n_qualified, n_emitted, n_skipped)"
            " VALUES ('2026-08-29', 'bull_low_vol', 15.2, 0.6, NULL, 100, 4, 2, 2)"
        )
        run_id = conn.execute("SELECT id FROM candidate_runs").fetchone()[0]
        rows = [
            # emitted — 노출 대상
            (run_id, "AAAA", "emitted", "momentum breakout", 0.91, 100.0, 93.0, 120.0, 140.0),
            (run_id, "BBBB", "emitted", "pullback add", 0.85, 50.0, 46.5, 60.0, 70.0),
            # skipped — 존재 자체가 보유/행동 신호. 응답에 나오면 안 된다.
            (run_id, "HELD", "skipped", "held (보유 중 — Phase 2 에서 add 모드 도입)", 0.7, None, None, None, None),
            (run_id, "SOLD", "skipped", "cooldown 5d (최근 SELL/trim 신호)", 0.6, None, None, None, None),
        ]
        conn.executemany(
            "INSERT INTO candidate_ledger (run_id, ticker, disposition, reason, score,"
            " entry, stop, tp1, tp2) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.execute("INSERT INTO macro (indicator, date, value, source) VALUES ('vix', '2026-08-29', 15.2, 'cboe')")
    return path


def _all_keys(obj) -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(k)
            keys |= _all_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            keys |= _all_keys(item)
    return keys


class TestExactResponseSchemas:
    """키 집합 **동치** — 넓히는 변경은 여기서 반드시 걸린다 (blocklist 교집합 방식은
    새 민감 키 이름을 못 잡는다)."""

    def test_certification_status(self, seeded_db):
        rows = readmodels.certification_status(db_path=seeded_db)
        assert len(rows) == 1
        assert set(rows[0]) == set(ALLOWED["certifications"])

    def test_buy_candidates(self, seeded_db):
        out = readmodels.latest_buy_candidates(db_path=seeded_db)
        assert set(out) == {"run", "candidates"}
        assert set(out["run"]) == set(ALLOWED["candidate_runs"])
        assert len(out["candidates"]) == 2
        for c in out["candidates"]:
            assert set(c) == set(ALLOWED["candidate_ledger"])

    def test_macro_facts(self, seeded_db):
        out = readmodels.macro_facts(db_path=seeded_db)
        assert set(out) == {"vix", "regime"}
        assert set(out["vix"]) == set(ALLOWED["macro"])
        assert set(out["regime"]) == {"regime", "timestamp", "caller"}


class TestSemanticLeakCases:
    """시드한 보유/행동 신호가 응답 **직렬화 전문**에 나타나지 않는다."""

    def _full_text(self, seeded_db) -> str:
        blob = {
            "cert": readmodels.certification_status(db_path=seeded_db),
            "cand": readmodels.latest_buy_candidates(db_path=seeded_db),
            "macro": readmodels.macro_facts(db_path=seeded_db),
        }
        return json.dumps(blob, ensure_ascii=False, default=str)

    def test_skipped_tickers_never_appear(self, seeded_db):
        text = self._full_text(seeded_db)
        assert "HELD" not in text, "skipped(보유) 티커가 응답에 노출됐다"
        assert "SOLD" not in text, "skipped(cooldown/매매활동) 티커가 응답에 노출됐다"
        assert "보유 중" not in text and "cooldown" not in text

    def test_no_forbidden_key_anywhere(self, seeded_db):
        blob = {
            "cert": readmodels.certification_status(db_path=seeded_db),
            "cand": readmodels.latest_buy_candidates(db_path=seeded_db),
            "macro": readmodels.macro_facts(db_path=seeded_db),
        }
        bad = _all_keys(blob) & FORBIDDEN_KEYS
        assert not bad, f"금지 키가 응답에 등장: {sorted(bad)}"

    def test_emitted_tickers_do_appear(self, seeded_db):
        """대조군 — 전부 떨구는 가짜 수정을 막는다."""
        out = readmodels.latest_buy_candidates(db_path=seeded_db)
        assert [c["ticker"] for c in out["candidates"]] == ["AAAA", "BBBB"]
        assert out["run"]["n_qualified"] == 4


class TestReadOnlyIsEngineEnforced:
    def test_readonly_connection_rejects_writes(self, tmp_path):
        """`readonly=True` 는 관행이 아니라 SQLite 가 막는다 — mode=ro + query_only."""
        from nuri.core.db import OperationalError

        path = tmp_path / "ro.db"
        init_db(path)
        with pytest.raises(OperationalError, match="readonly"):
            with get_db(path, readonly=True) as conn:
                conn.execute("INSERT INTO macro (indicator, date, value, source) VALUES ('x', 'd', 1, 's')")

    def test_writable_control(self, tmp_path):
        """대조군 — readonly=False 는 기존 동작 그대로."""
        path = tmp_path / "rw.db"
        init_db(path)
        with get_db(path) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value, source) VALUES ('x', 'd', 1, 's')")

    def test_readonly_never_creates_a_missing_db(self, tmp_path):
        """mode=ro 는 없는 파일을 만들지 않는다 — 유령 DB 생성은 쓰기 부수효과다.

        writable 경로처럼 열고 PRAGMA 만 걸면 `sqlite3.connect` 가 빈 파일을 만든다
        (codex P2 계열). 정직한 실패가 계약이다.
        """
        from nuri.core.db import OperationalError

        ghost = tmp_path / "does-not-exist.db"
        with pytest.raises(OperationalError):
            with get_db(ghost, readonly=True) as conn:
                conn.execute("SELECT 1")
        assert not ghost.exists(), "read-only 연결이 파일을 만들었다"

    def test_readonly_does_not_rewrite_journal_header(self, tmp_path):
        """DELETE-journal 사본을 readonly 로 읽어도 WAL 로 승격되지 않는다 (codex P2).

        writable 경로는 연결마다 `journal_mode=WAL` 을 걸어 **헤더를 고쳐 쓴다** —
        readonly 가 그 경로를 공유하면 "읽기 전용" 첫 호출이 이미 파일을 바꾼 뒤다.
        conftest 의 `_test_connect` 패치가 실 구현을 미러하므로 여기서 잠근 동작이
        프로덕션 `get_connection` 과 같은 계약이다 (짝: 아래 실구현 직접 검증).
        """
        import sqlite3 as _sqlite3  # noqa: F401 — 실구현 대조는 uri 연결로만, import 는 검증용 아님

        path = tmp_path / "copy.db"
        init_db(path)
        with get_db(path) as conn:
            conn.execute("PRAGMA journal_mode=DELETE")

        with get_db(path, readonly=True) as conn:
            conn.execute("SELECT 1").fetchone()
            mode_during = conn.execute("PRAGMA journal_mode").fetchone()[0]

        with get_db(path) as conn:
            pass  # writable 재개방은 WAL 로 되돌린다 — 그 전에 재야 한다

        assert mode_during.lower() == "delete", f"readonly 연결이 journal 을 바꿨다: {mode_during}"

    def test_real_get_connection_readonly_contract(self, tmp_path, monkeypatch):
        """conftest 패치가 아닌 **실제** `get_connection` 의 readonly 계약을 직접 검증.

        전역 픽스처가 get_connection 을 갈아끼우므로, 실구현은 원본 모듈에서 직접
        불러 확인한다 — 패치 미러가 낡아도 여기서 걸린다.
        """
        from nuri.core.db.connection import get_connection as real_get_connection

        path = tmp_path / "real.db"
        init_db(path)
        with get_db(path) as conn:
            conn.execute("PRAGMA journal_mode=DELETE")

        conn = real_get_connection(path, readonly=True)
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
            with pytest.raises(Exception, match="readonly"):
                conn.execute("INSERT INTO macro (indicator, date, value, source) VALUES ('x', 'd', 1, 's')")
        finally:
            conn.close()

        ghost = tmp_path / "real-ghost.db"
        with pytest.raises(Exception):
            real_get_connection(ghost, readonly=True)
        assert not ghost.exists()

    def test_every_readmodel_query_is_readonly(self):
        """AST — `nuri/mcp/` 의 모든 `query(...)` 호출에 `readonly=True` 키워드.

        하나라도 빠지면 그 호출만 쓰기 가능한 연결로 조용히 격하된다
        (db_path forwarding 과 같은 클래스의 누락 축)."""
        for py in MCP_DIR.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "query"):
                    continue
                kw = {k.arg: k.value for k in node.keywords}
                ok = "readonly" in kw and isinstance(kw["readonly"], ast.Constant) and kw["readonly"].value is True
                assert ok, f"{py.name}:{node.lineno} — query() 에 readonly=True 가 없다"


class TestStructuralSweeps:
    """보조 스윕 — 출력 계약 테스트가 1차, 이건 드리프트 조기 경보다."""

    def test_sql_references_only_allowed_tables(self):
        """SQL 문자열의 FROM/INTO 대상이 ALLOWED 키 집합과 일치 (양방향)."""
        # f-string SQL 은 AST 에서 JoinedStr 로 쪼개져 "FROM …" 조각에 SELECT 가 없다 —
        # 문자열 상수 전부를 이어 붙인 뒤 FROM 만 찾는다 (독스트링의 `table.column`
        # 언급은 FROM 뒤가 아니라 매치되지 않는다).
        sql_text = " ".join(
            n.value
            for py in MCP_DIR.rglob("*.py")
            for n in ast.walk(ast.parse(py.read_text(encoding="utf-8")))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        )
        referenced = set(re.findall(r"\bFROM\s+([a-z_]+)", sql_text))
        # schema_version: 기동 프로브(_schema_lag)의 마이그레이션 메타데이터 —
        # 사용자 데이터가 없는 유일한 예외. read model 이 아니라 ALLOWED 에 안 둔다.
        referenced -= {"schema_version"}
        assert referenced == set(ALLOWED), (
            f"SQL 테이블과 allowlist 불일치.\n  SQL에만: {sorted(referenced - set(ALLOWED))}\n"
            f"  allowlist에만: {sorted(set(ALLOWED) - referenced)}"
        )
        forbidden = {"portfolio", "trades", "positions", "decisions", "theses"}
        assert not (referenced & forbidden), f"holdings/행동 테이블 참조: {sorted(referenced & forbidden)}"

    def test_no_write_helper_and_no_network_import(self):
        """`nuri/mcp/` 는 쓰기 헬퍼·네트워크 서버 표면을 import 하지 않는다."""
        banned_prefixes = ("uvicorn", "fastapi", "socket", "http.server")
        for py in MCP_DIR.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [f"{node.module}.{a.name}" if node.module else a.name for a in node.names]
                for name in names:
                    assert not name.startswith(banned_prefixes), f"{py.name}: 금지 import {name}"
                    assert "upsert" not in name and "replace_portfolio" not in name, (
                        f"{py.name}: 쓰기 헬퍼 import {name}"
                    )

    def test_mcp_json_registers_stdio_without_binding_args(self):
        """`.mcp.json` 의 nuri-read 는 stdio 커맨드 — --port/--host 류가 없다."""
        cfg = json.loads((Path(__file__).resolve().parents[2] / ".mcp.json").read_text(encoding="utf-8"))
        entry = cfg["mcpServers"]["nuri-read"]
        joined = " ".join([entry["command"], *entry["args"]])
        assert "nuri.mcp.server" in joined
        assert "--port" not in joined and "--host" not in joined and "http" not in joined

    def test_mcp_json_ships_no_raw_db_server(self):
        """커밋된 기본값에 nuri-read 외 서버가 없다 (codex P1).

        raw SQLite MCP(mcp-server-sqlite)가 기본으로 실리면 임의 SQL 이
        portfolio/trades 에 닿아 Tier 1 경계가 각자의 로컬 설정에 의존하게 된다.
        ad-hoc 탐색은 개인 설정에 로컬로만 등록한다 — 동치 비교라 어떤 이름으로
        돌아와도 여기서 걸린다.
        """
        cfg = json.loads((Path(__file__).resolve().parents[2] / ".mcp.json").read_text(encoding="utf-8"))
        assert set(cfg["mcpServers"]) == {"nuri-read"}, (
            f"커밋된 MCP 서버 목록이 계약과 다르다: {sorted(cfg['mcpServers'])}"
        )

    def test_schema_lag_probe_is_readonly_and_detects_lag(self, tmp_path):
        """기동 프로브 (codex P1): lag 를 **읽기만으로** 감지 — 낡은 DB 를 고치지 않는다."""
        from nuri.mcp.server import _schema_lag

        path = tmp_path / "lagged.db"
        init_db(path)
        with get_db(path) as conn:
            conn.execute("DELETE FROM schema_version WHERE version > 10")
        before = path.stat().st_mtime_ns

        current, expected = _schema_lag(db_path=path)

        assert current == 10 and expected > 10, f"lag 미감지: {current}/{expected}"
        assert path.stat().st_mtime_ns == before, "프로브가 DB 를 건드렸다 — read-only 위반"
        fresh = tmp_path / "fresh.db"
        init_db(fresh)
        cur2, exp2 = _schema_lag(db_path=fresh)
        assert cur2 == exp2, "신선한 DB 에서 lag 오탐"
