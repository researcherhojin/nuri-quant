"""stdio MCP 서버 — Tier 1 read model 4종 노출 (#1306).

- **stdio 전용**: 네트워크 바인딩이 존재하지 않는다 — "외부 바인딩 부재" 수용 기준이
  설정이 아니라 구조로 성립한다. 클라이언트(Claude Code 등)가 `.mcp.json` 의
  `nuri-read` 항목으로 프로세스를 필요 시 띄운다.
- **read-only**: 쓰기 도구가 없고, 이 패키지는 `nuri.core.db` 의 `query()` 외에 어떤
  DB 표면도 import 하지 않는다 (잠금: `tests/mcp/test_boundary.py`).
- **로깅도 경계다**: 도구 인자·반환 행을 로그로 남기지 않는다 — stderr 로 새는 행이
  곧 유출이다.
- 기존 `nuri-db`(raw SQLite MCP, 현재 비활성) 대비 존재 이유: **정규화 + 민감 필드
  부재 보장**. raw 테이블 접근은 holdings 를 그대로 노출한다.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from nuri.mcp import readmodels

server = MCPServer(
    "nuri-read",
    instructions=(
        "nuri-quant 시스템 산출물의 비민감(Tier 1) read model. 매매 판단 질문에는 "
        "추측 대신 이 도구들을 조회할 것. 보유 수량·평단·계좌 정보는 설계상 존재하지 "
        "않는다 (Tier 2 별도 이슈). 응답을 public 매체(이슈·PR 등)에 옮길 때는 "
        "레포 privacy 규칙(ticker+손익% 조합 금지)을 적용할 것."
    ),
)


@server.tool()
def siege_status(limit: int = 5) -> list[dict[str, Any]]:
    """최근 SIEGE 3D 인증 판정 (certified/score/passed/failed/warnings/regime). 스칼라만."""
    return readmodels.certification_status(limit=limit)


@server.tool()
def buy_candidates(run_date: str | None = None) -> dict[str, Any]:
    """최신(또는 지정일) buy candidate run — 카운트 요약 + emitted 티커·entry/stop/tp1/tp2."""
    return readmodels.latest_buy_candidates(run_date=run_date)


@server.tool()
def macro_facts() -> dict[str, Any]:
    """VIX 최신값 + 최근 인증 시점의 regime (timestamp/caller 포함 — 신선도는 소비자 판단)."""
    return readmodels.macro_facts()


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
