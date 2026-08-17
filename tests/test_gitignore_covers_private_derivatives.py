"""민감 파일의 **파생 이름**까지 gitignore 가 막는지 잠근다 (#996).

Gotcha-Test Pair:
`.gitignore` 는 `config/portfolio.yaml` 을 **정확 경로**로만 막고 있었다. 그래서 편집 전
백업으로 만든 `config/portfolio.yaml.bak-20260803_163959` 가 무시되지 않고 `git status` 에
untracked 로 떴다 — `git add -A` 한 번이면 실보유 종목·수량·평단이 public repo 로 들어간다.
(2026-08-03 실측. 다행히 커밋된 적은 없어 히스토리는 깨끗했다.)

왜 놓쳤나: `*.bak` 과 `*.orig` 는 이미 막혀 있었다. 사람이 흔히 붙이는
`*.bak-<timestamp>` 만 그 패턴에 안 걸린다 — "백업은 막혀 있다" 는 인상은 맞았고
**한 칸 옆이 뚫려** 있었다. 도구(그리고 에이전트)가 타임스탬프 백업을 만드는 게 관례라
이 틈은 반복해서 밟힌다.

privacy 스캐너(`scripts/verify/check_privacy_leak.py`)는 **diff** 를 본다. untracked 파일은
diff 에 없으므로 이 계열을 못 잡는다 — 방어선이 gitignore 하나뿐이라 여기서 잠근다.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# 사람이/도구가 실제로 만드는 파생 이름들. 전부 무시돼야 한다.
MUST_BE_IGNORED = [
    # 보유 종목 — 종목·수량·평단
    "config/portfolio.yaml",
    "config/portfolio.yaml.bak",
    "config/portfolio.yaml.bak-20260803_163959",  # 실제로 발생한 이름
    "config/portfolio.yaml.orig",
    "config/portfolio.yaml.save",
    "config/portfolio.yaml.tmp",
    "config/portfolio_backup.yaml",
    # 크리덴셜
    ".env",
    ".env.bak-20260803_155436",
    ".env.save",
    # 개인 상태 / 내부 운영 문서
    "NEXT_SESSION.md",
    "NEXT_SESSION.md.bak",
    "docs/OPERATIONS.md",
    "docs/OPERATIONS.md.bak",
]

# 반대로 **추적돼야** 하는 것 — 과잉 차단 회귀 방지
MUST_NOT_BE_IGNORED = [
    "config/portfolio.example.yaml",
    "config/rules.yaml",
    "config/agents.yaml",
    "config/signals.yaml",
]


def _is_ignored(path: str) -> bool:
    """`git check-ignore` 로 판정 — 파일이 실재하지 않아도 패턴 판정은 된다."""
    return subprocess.run(["git", "check-ignore", "-q", path], check=False).returncode == 0


@pytest.mark.parametrize("path", MUST_BE_IGNORED)
def test_private_file_and_its_derivatives_are_ignored(path):
    """회귀 시나리오: 접두사 glob 을 정확 경로로 되돌리면 백업 파일이 커밋 가능해진다."""
    assert _is_ignored(path), f"{path} 가 gitignore 에 안 걸린다 — git add -A 한 번이면 public repo 로 나간다"


@pytest.mark.parametrize("path", MUST_NOT_BE_IGNORED)
def test_shared_config_stays_trackable(path):
    """차단 범위를 넓히다 공유돼야 할 파일까지 삼키면 안 된다."""
    assert not _is_ignored(path), f"{path} 는 추적돼야 하는데 gitignore 가 삼켰다"


class TestWritersAimInsideTheIgnoredArea:
    """위 테스트들은 **알려진 경로**가 막히는지 본다. 이건 반대쪽이다 —
    **쓰는 쪽이 막힌 경로를 겨누고 있는지** (#1062).

    `scripts/verify/verify.py` 는 `ROOT = Path(__file__).parent.parent` 로 루트를
    잡았는데, 파일이 `scripts/verify.py` 에서 `scripts/verify/verify.py` 로 옮겨질 때
    이 줄이 안 따라왔다. `ROOT` 가 `scripts/` 로 해소돼 리포트가
    `scripts/data/reports/<date>/` 에 쌓였다 — `data/reports/` 와 달리 gitignore 가
    안 걸리는 자리다.

    그 리포트에 실보유 데이터가 있다. `portfolio.csv` 는
    `account,ticker,...,quantity,avg_price,...,pnl_usd,pnl_pct` 를 담고,
    `check_privacy_leak.py` 를 겨누면 증권사명+종목+손익을 줄 단위로 잡아낸다
    (2026-08-17, 17개 파일 실측). `git add -A` 한 번이면 public repo 로 나간다.

    gitignore 목록을 아무리 늘려도 이 형태는 못 잡는다 — 목록에 **없는** 경로로
    쓰는 게 결함이기 때문이다. 그래서 writer 가 계산한 경로 자체를 본다.
    """

    def test_verify_report_dir_is_gitignored(self):
        """Gotcha-Test Pair: `parents[2]` 를 `parent.parent` 로 되돌리면 FAIL."""
        root = _verify_module().ROOT
        report_dir = Path(root) / "data" / "reports"
        rel = Path(report_dir).resolve().relative_to(REPO_ROOT)
        assert _is_ignored(f"{rel}/2026-01-01/portfolio.csv"), (
            f"verify.py 가 리포트를 {rel}/ 에 쓰는데 gitignore 가 거길 안 막는다 — "
            "실보유 종목·수량·손익 CSV 가 untracked 로 노출된다.\n"
            "gitignore 에 그 경로를 추가하지 말 것 — verify.py 의 ROOT 를 고칠 것 (#1062)."
        )

    def test_verify_root_is_the_repo_root(self):
        """카나리아 — 위 테스트는 `ROOT` 가 엉뚱해도 그 아래가 우연히 ignore 되면 통과한다."""
        assert Path(_verify_module().ROOT).resolve() == REPO_ROOT, (
            f"verify.py ROOT = {_verify_module().ROOT} (기대: {REPO_ROOT})"
        )


def _verify_module():
    """`scripts/verify/verify.py` 를 패키지 밖에서 로드한다 (스크립트라 import 경로가 없다).

    모듈 레벨 부작용은 `sys.path.insert` 와 `logging.basicConfig` 둘뿐이고, 무거운
    `nuri` import 는 전부 함수 안이라 로드가 싸다.
    """
    path = REPO_ROOT / "scripts" / "verify" / "verify.py"
    spec = importlib.util.spec_from_file_location("_verify_under_test", path)
    assert spec and spec.loader, f"{path} 를 로드할 수 없다"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
