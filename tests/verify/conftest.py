"""이 디렉터리는 문서 게이트를 테스트한다 — 그중 `scripts/doc/sync_doc_counts.sh` 는
검사기가 아니라 **in-place fixer** 다. 사본이 아니라 레포에 겨누면 실제 문서를 고쳐 쓴다.

`test_sync_does_more_than_print_its_banner` 하나가 override 없이 그걸 돌려서 **백엔드
테스트를 돌릴 때마다 실제 README/ARCHITECTURE/STRATEGY 가 조용히 재작성**됐다. 테스트는
통과하고 pytest 출력에 흔적이 없어 `git status` 를 볼 때까지 몰랐다.

여기 두 겹을 건다:

1. `_fixer_never_targets_the_real_repo` — `subprocess.Popen` 을 감싸 **실행 자체를 막는다.**
   `Popen` 이 `run`/`call`/`check_call`/`check_output` 의 공통 관문이라 한 곳만 잡으면
   argv 를 변수에 담든 헬퍼로 감싸든 전부 걸린다. 쓰기가 일어난 뒤가 아니라 **겨눈 순간**
   터지므로 문서가 sync 상태여도 발화한다 — 이게 결정론적 회귀 잠금이다.
   카나리아: `test_doc_claim_parity.py::TestFixerGuard` 가 실제로 위반을 시도해 본다.
2. `_repo_docs_stay_untouched` — fixer 대상 문서의 해시 대조. subprocess 를 안 거치는
   직접 쓰기(테스트가 `README.md` 를 파이썬으로 여는 경우)를 덮는 **보조** 트립와이어다.
   문서가 sync 면 안 울리므로 이쪽은 회귀 잠금이 아니다.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SYNC = REPO_ROOT / "scripts" / "doc" / "sync_doc_counts.sh"

# in-place fixer 집합은 **디렉터리가 아니라 동작**으로 유도한다 — `scripts/` 전체를 훑어
# `sed -i` 로 파일을 고쳐 쓰는 셸 스크립트만 고른다. 폴더 위치로 정의하면 읽기 전용 헬퍼가
# 그 폴더에 들어올 때 과잉 차단하고, fixer 가 이사가면 못 잡는다 (Codex 리뷰 2026-08-10).
# 실측 2026-08-10: `scripts/**/*.sh` 27개 중 해당 1개 (`sync_doc_counts.sh`).
# ⚠️ 유지보수 한계: `sed -i` 만 본다. 새 fixer 가 `perl -i` / `tee` / 리다이렉션 / `python -c`
# 로 고쳐 쓰면 **자동 등록되지 않는다** — 그런 fixer 를 추가할 땐 여기 패턴도 같이 넓힐 것.
# (리다이렉션을 지금 넣지 않는 이유: 로그·임시파일 쓰는 정상 스크립트가 통째로 걸린다.)
_FIXERS = sorted({p.name for p in (REPO_ROOT / "scripts").rglob("*.sh") if re.search(r"\bsed -i\b", p.read_text())})

# 카나리아 — 탐지가 눈이 멀면 가드가 빈 집합을 지키는 green dead gate 가 된다.
if not _FIXERS:
    raise RuntimeError("in-place fixer 를 하나도 못 찾았다 — `sed -i` 탐지가 scripts/ 와 어긋남")

# fixer 가 쓰는 파일 목록은 스크립트에서 직접 읽는다 — 손으로 적으면 드리프트한다.
# `update_claim <live_fn> <file> '<pattern>'`
_FIXER_TARGETS = sorted({m.group(1) for m in re.finditer(r"^update_claim\s+\S+\s+(\S+)", _SYNC.read_text(), re.M)})

# 카나리아 — 정규식이 눈이 멀면 해시 가드가 빈 목록을 지킨다. collection 단계에서 크게 터뜨린다.
if len(_FIXER_TARGETS) < 6:
    raise RuntimeError(f"update_claim 대상을 {len(_FIXER_TARGETS)}건만 파싱했다 — 정규식이 어긋남: {_SYNC}")


def fixer_aimed_at_real_repo(args, env) -> str | None:
    """이 실행이 in-place fixer 를 **실제 레포**에 겨눴으면 그 스크립트 이름을 돌려준다.

    argv 리스트가 아니라 **합친 커맨드 문자열**을 본다 — `shell=True` 로 넘긴 문자열도,
    `["bash", "-lc", "... sync_doc_counts.sh"]` 같은 중첩 셸도 같은 검사를 통과해야 한다
    (Codex 리뷰 2026-08-10 에서 이 두 형태가 뚫렸다).

    `scripts/_common.sh` 는 스크립트 자신의 레포 루트로 cd 하므로 `cwd=` 로는 사본을
    가리킬 수 없다 — `REPO_ROOT` env override 가 유일한 수단이고, 없으면 실제 레포다.
    """
    text = " ".join(str(a) for a in args) if isinstance(args, (list, tuple)) else str(args)
    hit = next((name for name in _FIXERS if name in text), None)
    if hit is None:
        return None
    effective = Path((env if env is not None else os.environ).get("REPO_ROOT", str(REPO_ROOT)))
    return hit if effective.resolve() == REPO_ROOT else None


@pytest.fixture
def fixer_guard():
    """가드의 판정 함수 — 카나리아 테스트가 실행 없이 경계를 확인할 때 쓴다."""
    return fixer_aimed_at_real_repo


@pytest.fixture(autouse=True)
def _fixer_never_targets_the_real_repo(monkeypatch):
    """`Popen.__init__` 을 감싼다 — 모듈 속성이 아니라 **클래스**를 잡는 이유는
    `from subprocess import Popen as X` 로 미리 묶어둔 별칭이 같은 클래스 객체라
    이쪽만 갈아끼우면 그 경로까지 덮이기 때문이다.
    """
    real_init = subprocess.Popen.__init__

    def guarded_init(self, args, *a, **kw):
        offender = fixer_aimed_at_real_repo(args, kw.get("env"))
        if offender:
            raise AssertionError(
                f"in-place fixer 를 실제 리포에 겨눴다: {offender}\n"
                "실행되면 README/ARCHITECTURE/STRATEGY 가 조용히 재작성된다. "
                "사본에서 돌릴 것 — `_run(SYNC, repo_copy)` (env 에 REPO_ROOT override)."
            )
        return real_init(self, args, *a, **kw)

    monkeypatch.setattr(subprocess.Popen, "__init__", guarded_init)


def _digest() -> dict[str, str]:
    return {
        rel: hashlib.sha256((REPO_ROOT / rel).read_bytes()).hexdigest()
        for rel in _FIXER_TARGETS
        if (REPO_ROOT / rel).exists()
    }


@pytest.fixture(autouse=True)
def _repo_docs_stay_untouched():
    before = _digest()
    yield
    changed = sorted(rel for rel, h in _digest().items() if before.get(rel) != h)
    assert not changed, (
        "테스트가 실제 리포의 문서를 수정했다: "
        + ", ".join(changed)
        + "\ndoc fixer 는 사본에서만 돌릴 것 — `_run(SYNC, repo_copy)` (REPO_ROOT env override)."
    )
