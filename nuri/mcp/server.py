"""stdio MCP 서버 — Tier 1 read model 3종 노출 (#1306; `siege_status` 는 #1619 로 제거).

- **stdio 전용**: 네트워크 바인딩이 존재하지 않는다 — "외부 바인딩 부재" 수용 기준이
  설정이 아니라 구조로 성립한다. 클라이언트(Claude Code 등)가 `.mcp.json` 의
  `nuri-read` 항목으로 프로세스를 필요 시 띄운다.
- **read-only**: 쓰기 도구가 없고, 이 패키지는 `nuri.core.db` 의 `query()` 외에 어떤
  DB 표면도 import 하지 않는다 (잠금: `tests/mcp_server/test_readmodels_privacy.py::TestStructuralSweeps::test_no_write_helper_and_no_network_import`).
- **로깅도 경계다**: 도구 인자·반환 행을 로그로 남기지 않는다 — stderr 로 새는 행이
  곧 유출이다.
- 기존 `nuri-db`(raw SQLite MCP, 현재 비활성) 대비 존재 이유: **정규화 + 민감 필드
  부재 보장**. raw 테이블 접근은 holdings 를 그대로 노출한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from nuri.mcp import readmodels, source

server = MCPServer(
    "nuri-read",
    instructions=(
        "nuri-quant 시스템 산출물의 비민감(Tier 1) read model. 매매 판단 질문에는 "
        "추측 대신 이 도구들을 조회할 것. 먼저 data_freshness 로 출처와 신선도를 확인하고, "
        "stale 이면 결과를 현재 상태로 제시하지 말고 그 사실과 최신 시각을 함께 밝힐 것. "
        "보유 수량·평단·계좌 정보는 설계상 존재하지 않는다 (Tier 2 별도 이슈). 응답을 "
        "public 매체(이슈·PR 등)에 옮길 때는 레포 privacy 규칙(ticker+손익% 조합 금지)을 적용할 것."
    ),
)


@server.tool()
def buy_candidates(run_date: str | None = None) -> dict[str, Any]:
    """최신(또는 지정일) buy candidate run — 카운트 요약 + emitted 티커·entry/stop/tp1/tp2."""
    return readmodels.latest_buy_candidates(run_date=run_date, db_path=source.resolve_source().path)


@server.tool()
def macro_facts() -> dict[str, Any]:
    """VIX 최신값 + 최근 후보 run 의 regime (run_date 포함 — 신선도는 data_freshness 로 확인)."""
    return readmodels.macro_facts(db_path=source.resolve_source().path)


@server.tool()
def data_freshness() -> dict[str, Any]:
    """이 서버가 읽는 DB 의 출처(replica/local/env_override)·파일 나이·최신 데이터 시각·stale 판정.

    다른 도구의 결과를 "현재" 로 제시하기 전에 먼저 확인한다. 경로는 반환하지 않는다.
    """
    return source.freshness(source.resolve_source())


def _schema_lag(db_path: "Path | None" = None) -> tuple[int, int]:
    """(적용된 버전, 코드가 기대하는 버전) — **읽기 전용** 프로브.

    이 서버는 read-only 라 `init_db()`(쓰기)를 대신 실행하지 않는다. 대신 lag 를
    기동 시 stderr 로 알려서, 낡은 스키마의 첫 조회가 내는 `no such column` 이
    "서버 버그" 가 아니라 "마이그레이션 미적용" 으로 읽히게 한다 (codex P1 —
    `nuri/core/CLAUDE.md` 의 CLI-미마이그레이션 함정; 해소는 쓰기 권한이 있는
    경로(`init_db`/scheduler 기동)의 몫이다).
    """
    from nuri.core.db import DatabaseError, query
    from nuri.core.db_migrations import _MIGRATIONS

    expected = len(_MIGRATIONS)
    try:
        rows = query("SELECT MAX(version) AS v FROM schema_version", db_path=db_path, readonly=True)
        current = rows[0]["v"] or 0
    except DatabaseError:
        # 테이블/파일 부재(OperationalError) 또는 전송이 끊긴 반쪽 replica(손상) — 기동은 계속해
        # data_freshness 가 그 사실을 보고하게 한다. 여기서 죽으면 어떤 도구도 뜨지 않는다.
        current = 0
    return current, expected


def main() -> None:
    import sys

    src = source.resolve_source()
    current, expected = _schema_lag(src.path)
    fresh = source.freshness(src)
    if fresh["stale"]:
        print(f"[nuri-read] 경고: 출처({src.kind})가 낡았다 — {'; '.join(fresh['stale_reasons'])}", file=sys.stderr)
    if current < expected:
        print(
            f"[nuri-read] 경고: 스키마 {current}/{expected} — 마이그레이션 미적용 DB. "
            "일부 조회가 'no such column' 으로 실패할 수 있다. 해소: 쓰기 경로에서 init_db() "
            "(read-only 서버는 대신 실행하지 않는다)",
            file=sys.stderr,
        )
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
