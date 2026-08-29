"""추적 파일에 절대 경로 심볼릭 링크가 없음을 잠근다 (Gotcha-Test Pair, #1316).

`d1bfc4a3` (#1313) 이 `.venv` 를 mode 120000 심볼릭 링크(타깃: 로컬 절대 경로)로
커밋했다. `.gitignore` 의 `.venv/` 는 **끝 슬래시 탓에 디렉터리만 매치**해서,
worktree 세션이 만든 `.venv` "링크" 는 ignore 를 통과해 `git add -A` 에 쓸려 들어갔다.

피해가 조용하고 파괴적이다: ignored 디렉터리는 git 이 clobber 가능하므로, 이 커밋을
pull 한 모든 체크아웃에서 **실제 venv 디렉터리가 삭제되고 링크로 교체**됐다 —
Mac mini 는 링크가 자기 경로를 가리켜 자기참조 루프가 됐고 (`uv sync` os error 62,
scheduler down), MBP 는 실제 venv 를 잃었다. 교체 후 `git status` 는 clean 이라
**아무 신호가 없다**.

두 축을 나눠 잠근다:
- 인덱스 축: 절대 경로 타깃 심볼릭 링크는 머신 종속이라 public repo 에 존재할 수 없다
- .gitignore 축: venv 패턴이 심볼릭 링크 "타입" 도 매치해야 한다 (끝 슬래시 금지)
"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def _tracked_symlinks() -> list[tuple[str, str]]:
    """인덱스의 (경로, 링크 타깃) 목록 — mode 120000 만."""
    out = _git("ls-files", "-s").stdout
    links = []
    for line in out.splitlines():
        mode, sha, _rest = line.split(maxsplit=2)
        if mode != "120000":
            continue
        path = line.split("\t", 1)[1]
        target = _git("cat-file", "blob", sha).stdout
        links.append((path, target))
    return links


def test_venv_is_not_tracked():
    """`.venv` 인덱스 등재는 어떤 mode 든 결함이다 — #1316 의 결함 그 자체.

    `git update-index --cacheinfo` 로 되살리든 ignore 를 뚫고 add 되든, 여기서 잡힌다.
    """
    tracked = _git("ls-files", "--", ".venv", "venv").stdout.strip()
    assert tracked == "", (
        f".venv/venv 가 git 에 추적되고 있다: {tracked!r} — 이 커밋을 pull 하는 모든 "
        "체크아웃의 실제 venv 가 파괴된다 (#1316, mini production down 실측)"
    )


def test_no_tracked_symlink_with_absolute_target():
    """절대 경로 타깃 심볼릭 링크는 머신 종속 — public repo 에 존재할 수 없다.

    `.venv` 사고의 클래스 잠금: 타깃이 `/Users/...` 인 링크는 다른 머신에서 깨지거나
    (최악) 자기 경로와 일치해 자기참조 루프가 된다. 상대 경로 링크는 허용 (현재 0건).
    """
    bad = [(p, t) for p, t in _tracked_symlinks() if t.startswith("/")]
    assert bad == [], (
        f"절대 경로 타깃 심볼릭 링크가 추적되고 있다: {bad} — 머신 종속 경로는 fresh checkout 을 깨뜨린다 (#1316)"
    )


def test_gitignore_venv_pattern_matches_symlink_type(tmp_path):
    """레포의 .gitignore 가 `.venv` **심볼릭 링크**를 ignore 하는지 실행으로 확인.

    끝 슬래시(`.venv/`)로 되돌리면 링크가 `??` 로 노출되어 FAIL — 패턴 형태를
    grep 하지 않고 git 의 실제 매칭 동작으로 잠근다 (dead-gate 계열 교훈).
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text((REPO_ROOT / ".gitignore").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / ".venv").symlink_to(tmp_path / "nonexistent-target")

    status = _git("status", "--porcelain", "--", ".venv", cwd=tmp_path).stdout.strip()
    assert status == "", (
        f".venv 심볼릭 링크가 ignore 되지 않는다: {status!r} — "
        ".gitignore 의 venv 패턴에 끝 슬래시가 돌아왔는지 확인 (#1316)"
    )
