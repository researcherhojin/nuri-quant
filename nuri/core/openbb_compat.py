"""openbb 단일 진입점 — 실패한 import 를 프로세스당 한 번만 지불한다 (#1477).

`from openbb import obb` 는 현재 모든 머신에서 실패한다 (openbb 4.7.2 + openbb-core 1.6.13,
`router.get_command_map` 의 `_IncludedRouter has no attribute 'path'`). 실패한 패키지 import 는
`sys.modules` 에 남지 않으므로 호출 지점마다 다시 시도했고, 그 한 번이 MBP 1.6s · mini 2.6s ·
CI(branch coverage, 4-core) 13~17s 다 — #1475 의 덩어리 테스트 두 개가 정확히 그 비용이었다.

여기서 한 번 시도하고 실패를 기억한다. 실패 뒤에는 `sys.modules["openbb"].obb` 만 읽는다 — 테스트가
꽂은 스텁은 그대로 쓰이고(실제 실패는 sys.modules 에 `openbb` 를 남기지 않는다), `obb` 가 없는
부분 모듈이 남아 있어도 재시도하지 않는다 (Codex P3, 2026-09-08).

호출 지점은 이 모듈만 거친다: `tests/core/test_openbb_compat.py::TestSoleImporter` 가 AST 로 잠근다.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import Any

logger = logging.getLogger(__name__)

_FAILED = False
_LOCK = threading.Lock()  # stock.py 의 10-worker 풀이 첫 배치에서 동시에 들어온다 — 시도는 한 스레드만


def get_obb() -> Any | None:
    """`openbb.obb` 또는 None. 실패는 프로세스당 한 번만 시도하고 한 번만 WARNING."""
    global _FAILED
    with _LOCK:
        if _FAILED:
            return getattr(sys.modules.get("openbb"), "obb", None)
        try:
            from openbb import obb
        except Exception as exc:  # noqa: BLE001 — ImportError 만이 아니라 openbb 내부의 AttributeError 도 온다
            _FAILED = True
            logger.warning(
                "openbb 를 쓸 수 없다 — 이 프로세스에서는 다시 시도하지 않는다 (%s: %s)", type(exc).__name__, exc
            )
            return None
        return obb
