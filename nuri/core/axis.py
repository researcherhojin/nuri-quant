"""Alpha / Portfolio axis helpers — PR B (codex bubble-bear #2).

PR A (#429) 가 `recommendations` 테이블에 `alpha_action` / `portfolio_action`
컬럼을 도입하고 writer (risk_agent + consensus) 가 axis 를 채우도록 했다.
PR B 는 **read path** 를 axis-native 로 전환해 writer discipline 의존을 제거.

Semantic (codex Plan Q1-B dual-accept):
- `alpha_action == "FLAT"` → 명시적 alpha SELL 신호. urgent / check 경로 진입.
- `alpha_action is None` + `action == "SELL"` → pre-migration-22 legacy row.
  Back-compat 허용 — 현재 bug 재발 아님. PR C 에서 writer 완전 마이그레이션 후 strict mode 로.
- `alpha_action == "LONG"` / `"SHORT"` → BUY/SHORT signal.
- 그 외 (None + action != SELL, 또는 FLAT 아닌 값) → alpha 신호 **없음** → default-safe (hold/portfolio bucket).

이 helper 가 존재하는 이유:
- `nuri/api/routes/actions.py` + `nuri/api/routes/dashboard.py` 양쪽이 동일 semantic 을
  사용해야 한다 (codex Plan Scope 검증). 중복 구현 피하려면 shared helper 가 필수.
- Strict mode 전환 시 한 곳만 수정하면 모든 consumer 가 자동 반영.
"""

from __future__ import annotations


def is_alpha_flat_sell(
    alpha_action: str | None,
    action: str | None,
    *,
    strict: bool = False,
) -> bool:
    """이 row 가 alpha-driven SELL 신호인가.

    Args:
        alpha_action: "LONG" | "SHORT" | "FLAT" | None (DB row 의 `alpha_action`).
        action: "BUY" | "SELL" | "HOLD" | None (legacy column).
        strict: True 면 `alpha_action=="FLAT"` 만 허용. False (default) 는
            pre-migration NULL + legacy SELL 도 허용 (back-compat).

    Returns:
        True: urgent/check 경로에서 SELL semantic 으로 취급.
        False: alpha 신호 없음 — default-safe (hold / portfolio bucket 으로 route).
    """
    if alpha_action == "FLAT":
        return True
    if strict:
        return False
    # Back-compat: pre-PR-A writer 는 alpha_action 을 설정 안 함.
    # tracker.py 와 candidates.py 가 PR B 커밋 2 에서 axis 를 채우면 이 분기 필요
    # 건수는 점진 감소. strict=True 전환은 PR C 이후.
    return alpha_action is None and action == "SELL"


def is_alpha_long_buy(
    alpha_action: str | None,
    action: str | None,
    *,
    strict: bool = False,
) -> bool:
    """이 row 가 alpha-driven BUY 신호인가.

    `is_alpha_flat_sell` 의 buy side 대칭. `alpha_action="LONG"` 또는 legacy
    `action="BUY"` (strict=False).
    """
    if alpha_action == "LONG":
        return True
    if strict:
        return False
    return alpha_action is None and action == "BUY"


def derive_alpha_action(action: str | None) -> str | None:
    """Legacy `action` 으로부터 `alpha_action` 값을 derive (writer helper).

    candidates.py E-1 / tracker.py E-2 가 PR B 에서 writer discipline 확보 시 사용.
    consensus.py `save_to_recommendations` 는 이미 동일 mapping 을 inline 구현 중
    (PR A, consensus.py:596-627) — 여기 heavy refactor 는 PR C.

    Mapping:
        "BUY"  → "LONG"
        "SELL" → "FLAT"
        "HOLD" → None (alpha 중립)
        기타    → None
    """
    if action == "BUY":
        return "LONG"
    if action == "SELL":
        return "FLAT"
    return None
