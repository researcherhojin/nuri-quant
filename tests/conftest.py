"""Global test fixtures — yfinance mock + CI tmpfs SQLite 호환성 + 프로덕션 DB 격리."""

import shutil
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# 프로덕션 DB 격리 — 모든 테스트
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def _schema_db(tmp_path_factory):
    """스키마만 있는 빈 DB 를 세션당 **한 번** 만든다.

    테스트마다 `init_db()` 를 부르면 70.8ms × 약 6,900 테스트 = 8분이 그냥
    날아간다 (2026-08-14 실측). 파일 복사는 0.5ms 라 100배 이상 싸다.

    ## 마지막에 WAL 을 끄는 이유 (#1080)

    `init_db` 는 **진짜** `get_connection` 을 탄다 — 이 픽스처는 session scope 라
    function scope 의 `_force_no_wal` 보다 먼저 돈다. 그래서 `PRAGMA journal_mode=WAL`
    이 걸리고, journal_mode 는 **파일에 남는 속성**이라 `shutil.copy` 로 만든 모든
    격리 사본이 WAL 상태로 시작한다.

    그러면 `_force_no_wal` 의 `_test_connect` 가 커넥션마다 WAL→MEMORY 전환을 하게
    되는데, 그 전환은 **EXCLUSIVE 락을 요구하고 `busy_timeout` 이 적용되지 않는다**.
    같은 파일에 쓰기 락을 쥔 커넥션이 하나라도 있으면 커넥션 **생성 자체**가
    `database is locked` 로 죽는다 — 재시도 없이 즉시.

    실측 (같은 스키마, 다른 커넥션이 `BEGIN IMMEDIATE` 보유, 30회 시도):

        WAL 사본    → OperationalError 30/30
        DELETE 사본 → OperationalError  0/30

    DELETE 로 되돌려두면 `journal_mode=MEMORY` 가 락 없는 no-op 급 전환이 되어
    이 실패 경로가 사라진다. `busy_timeout` 을 앞으로 옮기는 것으로는 안 된다 —
    그것도 30/30 으로 실패한다(실측). 고칠 곳은 커넥션이 아니라 **원본의 모드**다.
    """
    from nuri.core.db import get_db, init_db

    path = tmp_path_factory.mktemp("schema") / "schema.db"
    init_db(path)
    # `init_db` 가 남긴 WAL 을 되돌린다. 사본이 상속하는 건 이 시점의 모드다.
    with get_db(path) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
    return path


@pytest.fixture(autouse=True)
def _isolate_from_production_db(_schema_db, tmp_path_factory, monkeypatch):
    """모든 테스트의 기본 DB 를 tmp 사본으로 돌린다.

    왜 전역인가
    -----------
    `db_path` 인자를 안 받는 프로덕션 함수가 많아서, 테스트가 아무리 조심해도
    전역 `DB_PATH` 로 새어 들어간다. 2026-08-14 실측: `tests/quant` 를 고친
    **뒤에도** 223개 테스트가 실제 `data/portfolio.db` 를 **7,587회** 열고
    있었다 (35개 파일, 11개 디렉터리).

    그게 낳은 실제 피해:
    - `test_high_vol_no_stats_truncates` 간헐 실패. 다른 워커가 `init_db()` 로
      EXCLUSIVE 락을 `busy_timeout=5000` 보다 오래 잡으면
      `sqlite3.OperationalError: database is locked` 가 난다 (재현 확인).
    - `test_macro_payload_carries_coverage` 는 tmp DB 에 seed 해놓고
      **프로덕션 데이터를 보고 통과**하고 있었다 — 초록이 거짓이었다.
    - `tests/agents/test_execution_firewall.py` 가 로컬 `discord_outbox` 에
      가짜 incident 17행을 몇 달간 써넣었다 (Mac mini 는 무사).

    223건을 하나씩 고치는 대신 기본값을 바꾼다. `_resolve_db_path` 가 매번
    `nuri.core.db.DB_PATH` 를 조회하므로(connection.py:39-43) 이 한 줄이
    `db_path` 를 안 받는 함수까지 전부 덮는다.

    개별 `db_path` / `db_path_mp` 픽스처는 그대로 동작한다 — 명시 인자가 우선이고,
    `db_path_mp` 는 같은 전역을 자기 것으로 다시 덮는다.

    ⚠️ 격리 DB 는 `tmp_path` 가 **아닌** 곳에 둔다. `tmp_path` 에 두면 "이 작업으로
    파일이 안 생겼는지" 를 `list(dir.iterdir()) == []` 로 확인하는 테스트가 우리
    DB 파일을 보고 깨진다 (`test_discord_inbound.py::test_returns_none_for_off_channel`
    에서 실제로 발생). 테스트가 들여다보는 공간을 픽스처가 침범하면 안 된다.
    """
    import nuri.core.db as db_mod

    path = tmp_path_factory.mktemp("isolated_db") / "portfolio.db"
    shutil.copy(_schema_db, path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# 프로덕션 DB 접근 금지 가드
# ─────────────────────────────────────────────────────────────────────────────
_REAL_DB = Path(__file__).resolve().parents[1] / "data" / "portfolio.db"


class _ProductionDBTouched(BaseException):
    """`Exception` 이 아니라 `BaseException` 을 상속한다 — **일부러**.

    프로덕션 코드에는 광범위 `except Exception` 이 많다(`gather_context` 는
    섹션마다 감싼다). `AssertionError` 로 던지면 그 핸들러가 가드를 삼켜서,
    테스트는 초록인데 프로덕션 DB 는 그대로 읽힌다 — 실제로 그렇게 통과하는 걸
    확인했다 (2026-08-14, `test_gather_context_all_failures_graceful`).

    백스톱이 삼켜지면 백스톱이 아니다. `BaseException` 은 `except Exception` 을
    통과해 pytest 까지 올라간다.
    """


@pytest.fixture(autouse=True)
def _forbid_production_db(monkeypatch):
    """실 `data/portfolio.db` 를 여는 순간 그 테스트를 **즉시** 실패시킨다.

    왜 관측이 아니라 차단인가
    -------------------------
    프로덕션 DB 를 읽는 테스트는 조용히 통과한다. 초록이라 아무도 안 본다.
    실제로 일어난 일 (2026-08-14 실측):

    - `tests/quant` 의 `TestMapStrategySpecialAndFallback` 7개가 `map_regime_to_strategy()` 를
      `db_path` 없이 불러 `analyze_signal_by_regime(None)` → `_get_vix()` 가
      SPY 행마다 도는 바람에 **테스트당 커넥션 1,118회 / 2.25초**를 썼다.
      그리고 다른 테스트가 같은 파일에 **쓴다** (`tests/CLAUDE.md`) — `-n auto`
      로 워커가 붙으면 읽는 쪽이 깨진다. `test_high_vol_no_stats_truncates` 가
      전체 실행 5회 중 1회 실패했고 단독 실행은 늘 통과했다. 원인을 찾는 데
      든 시간이 고치는 데 든 시간보다 훨씬 길었다.
    - `test_macro_payload_carries_coverage` 는 tmp DB 에 seed 해놓고 정작
      **프로덕션 데이터를 보고 통과**하고 있었다. 통과가 거짓이었다.

    이 가드는 `_isolate_from_production_db` 의 **백스톱**이다. 격리가 어떤 이유로든
    안 걸리는 경로가 생기면, 조용히 프로덕션으로 새는 대신 여기서 터진다.

    쓰기가 아니라 **여는 순간** 터뜨린다 — 읽기만 해도 위 두 문제가 다 생기고,
    쓰기까지 기다리면 이미 느려진 뒤다. (`tests/verify/conftest.py` 의 문서
    fixer 가드와 같은 설계: 피해가 난 뒤가 아니라 겨눈 순간.)

    빠져나갈 구멍: 정말 프로덕션 DB 가 필요하면 이 픽스처를 override 할 것.
    조용히 우회하지 말고 이유를 그 자리에 적어야 한다.
    """
    import nuri.core.db.connection as conn_mod

    real = str(_REAL_DB)
    original = conn_mod.sqlite3.connect

    def guarded(path, *args, **kwargs):
        if str(path) == real:
            raise _ProductionDBTouched(
                f"테스트가 프로덕션 DB 를 열었다: {path}\n"
                "tmp DB 를 쓸 것 — 대상 함수가 db_path 인자를 받으면 `db_path` 픽스처를,\n"
                "전역 DB_PATH 를 읽으면 `db_path_mp` 픽스처를 쓴다."
            )
        return original(path, *args, **kwargs)

    monkeypatch.setattr(conn_mod.sqlite3, "connect", guarded)


@pytest.fixture(autouse=True)
def _force_no_wal(monkeypatch):
    """모든 테스트에서 SQLite를 MEMORY journal mode로 강제.

    배경: CI Linux tmpfs(/tmp)에서 다음 두 문제 발생:
    1. WAL 파일이 다른 연결에 보이지 않음 (mmap 비호환)
    2. journal_mode=OFF + 별도 connection 간 INSERT visibility 손실
       (synchronous도 같이 OFF 되어 fsync 안 됨 → tmpfs 캐시 비일관성)

    해결: journal_mode=MEMORY
    - 롤백 journal을 RAM에 유지 (빠름, 디스크 I/O 없음)
    - 트랜잭션 의미는 보존 → INSERT 후 다른 connection에서 즉시 보임
    - tmpfs/일반 fs 모두 호환

    영향: TestGate / TestGate_R23 / TestStockCollectorCoverage 등
    별도 connection 간 visibility 의존 테스트가 안정화됨.
    """
    import sqlite3

    import nuri.core.db as db_mod

    def _test_connect(dp=None):
        path = dp or db_mod.DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        # MEMORY: rollback journal in RAM, preserves transaction semantics
        # (NORMAL synchronous → fsync on commit → cross-connection visibility)
        conn.execute("PRAGMA journal_mode=MEMORY")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    monkeypatch.setattr(db_mod, "get_connection", _test_connect)


@pytest.fixture(autouse=True)
def mock_yfinance(monkeypatch):
    """모든 테스트에서 yfinance.download와 Ticker를 mock."""
    import pandas as pd

    class MockTicker:
        def __init__(self, ticker):
            self.ticker = ticker
            self.upgrades_downgrades = None
            self.earnings_history = None
            self.insider_transactions = None
            self.recommendations = None

    def mock_download(*args, **kwargs):
        return pd.DataFrame()

    try:
        import yfinance

        monkeypatch.setattr(yfinance, "download", mock_download)
        monkeypatch.setattr(yfinance, "Ticker", MockTicker)
    except ImportError:
        pass


# ⚠️ 이 가드의 회귀 테스트는 `tests/test_production_db_guard.py` 에 있다.
# 여기 두면 **수집되지 않는다** — pytest 의 `python_files` 기본값이 `test_*.py` 라
# conftest.py 는 플러그인으로 import 될 뿐 테스트 모듈이 아니다. 파일을 인자로
# 명시하면 수집돼서 "돌려서 확인했다"는 착각을 만든다 (2026-08-14 실측).
