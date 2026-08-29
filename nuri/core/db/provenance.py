"""평가 결과 행의 evidence 바인딩 (#1305).

원장 행(backtest / walk-forward / decision_outcomes)이 "어느 코드·어느 설정으로
만들어졌나"를 self-measured 로 붙인다 — 귀속은 자기신고가 아니다 (#1115).
모르면 **None** — 지어내면 귀속이 거짓이 되어, 철회된 산출물을 구분하려고 붙이는
필드가 있느니만 못해진다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: `code_rev()` 프로세스 캐시. 미조회 상태를 None 과 구분해야 해서 sentinel 을 쓴다 —
#: git 없는 환경의 정답이 None 이라, None 을 미조회로 읽으면 매 행마다 재시도한다.
_CODE_REV_UNSET = object()
_CODE_REV_CACHE: object | str | None = _CODE_REV_UNSET


def code_rev() -> str | None:
    """이 행을 만든 코드 리비전 (짧은 git SHA, dirty 면 `-dirty` 접미).

    없으면 **None** — 지어내지 않는다. tarball 설치나 git 없는 환경에서는 알 수 없다.

    ## 왜 필요한가 (#1115)

    `backtests.id=3` 은 `p_value: 0.169` 를 담고 있다. 그 행이 쓰인 지 6시간 31분 뒤
    커밋 `84a5e36` 이 그 값을 철회했다 — permutation null 이 퇴화해 있었고, 정정값은
    0.791 이었다. **정정된 run 은 저장된 적이 없다.** 이 테이블은 strategy_id 마다 행이
    정확히 1개라 그 행을 밀어낼 신규 행도 없고, `nuri/api/routes/research.py` 는 지금도
    그 숫자를 현재 증거로 서빙한다.

    핵심은 낡은 행 자체가 아니다. **행이 어느 코드로 만들어졌는지 말할 수 없다**는 것이다.
    망가진 것으로 판명된 코드가 낸 숫자와 멀쩡한 숫자가 구분되지 않고, 철회는 원장이
    표현할 수 없는 사건이 된다. 리비전이 붙으면 소비자가 "이 행은 null 수정 이전"이라고
    말할 수 있다.

    이미 저장된 행을 고치는 건 코드가 아니라 프로덕션 DB 에서 할 일이다(재실행 후 저장,
    또는 삭제) — 여기서 하는 건 앞으로의 행을 귀속 가능하게 만드는 것뿐이다.
    """
    global _CODE_REV_CACHE

    # 프로세스당 1회만 조회한다 (Codex P2). `save_backtest` 는 `variant_walkforward` ·
    # `exit_walkforward` 의 루프 안에서 행마다 불리는데, 매번 `git status --porcelain`
    # 을 돌리면 워크트리 전체 스캔이 행 수만큼 반복된다. 리비전은 프로세스 수명 동안
    # 바뀌지 않으므로 재조회할 이유가 없다.
    if _CODE_REV_CACHE is not _CODE_REV_UNSET:
        return _CODE_REV_CACHE  # type: ignore[return-value]

    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=_REPO_ROOT,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        _CODE_REV_CACHE = None
        return None
    rev = out.stdout.strip()
    if not rev:
        _CODE_REV_CACHE = None
        return None
    try:
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=_REPO_ROOT,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        _CODE_REV_CACHE = rev
        return rev
    _CODE_REV_CACHE = f"{rev}-dirty" if dirty.stdout.strip() else rev
    return _CODE_REV_CACHE


#: v1 closure — **동결** (#1305, Codex challenge P1). 같은 컬럼명 아래에서 이 목록이
#: 바뀌면 행 간 비교가 불능이 되고 cherry-pick 소재가 된다. 파일을 더하거나 빼려면
#: closure 를 바꾸는 게 아니라 `execution_config_sha_v2()` + 새 컬럼으로 간다.
#:
#: 구성: 투자 룰 3종 + walk-forward 사전등록 설정 4종 (Codex review P2 — backtests /
#: walkforward_runs 행은 후자에도 좌우되므로, 빼면 사전등록 설정 변경이 같은 sha 로
#: 다른 결과를 낸다). `config/portfolio.yaml` 은 제외 — gitignored 개인 데이터라
#: 머신마다 존재/내용이 달라 sha 가 코드·룰이 아닌 배포 위치를 재게 된다.
_CONFIG_CLOSURE_V1: tuple[str, ...] = (
    "config/rules.yaml",
    "config/agents.yaml",
    "config/signals.yaml",
    "config/walkforward.yaml",
    "config/walkforward_variants.yaml",
    "config/walkforward_exits.yaml",
    "config/walkforward_exits_growth.yaml",
)

_CONFIG_SHA_UNSET = object()
_CONFIG_SHA_CACHE: object | str | None = _CONFIG_SHA_UNSET


def execution_config_sha_v1() -> str | None:
    """실행 시점 투자 설정 closure 의 내용 해시 (32 hex).

    closure 는 `_CONFIG_CLOSURE_V1` 로 동결 — rules + agents + signals. 셋 중 하나라도
    없으면 closure 를 말할 수 없으므로 **None** (부분 해시는 다른 closure 의 해시와
    구분이 안 되는 제3의 값이라 지어내는 것과 같다).

    파일명을 구분자와 함께 해시에 넣는다 — 내용만 이어붙이면 파일 경계 이동
    (A 끝 ↔ B 앞) 이 같은 해시를 낸다.
    """
    global _CONFIG_SHA_CACHE

    # code_rev 와 같은 이유의 프로세스 캐시: walk-forward 루프가 행마다 부르고,
    # 설정 파일은 프로세스 수명 동안 그 프로세스의 동작을 바꾸지 못한다(기동 시 로드).
    if _CONFIG_SHA_CACHE is not _CONFIG_SHA_UNSET:
        return _CONFIG_SHA_CACHE  # type: ignore[return-value]

    h = hashlib.sha256()
    for rel in _CONFIG_CLOSURE_V1:
        path = _REPO_ROOT / rel
        try:
            content = path.read_bytes()
        except OSError:
            _CONFIG_SHA_CACHE = None
            return None
        h.update(rel.encode())
        h.update(b"\x00")
        h.update(content)
        h.update(b"\x00")
    _CONFIG_SHA_CACHE = h.hexdigest()[:32]
    return _CONFIG_SHA_CACHE
