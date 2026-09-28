"""CI 의 venv 캐시가 **자족적**이고, `cache-hit` 을 신뢰하지 않는지 잠근다 (#1534).

`.venv/bin/python` 은 인터프리터로 가는 **심링크**다. ubuntu-26.04 에는 시스템 python3.12 가
없어(시스템은 3.14) uv 가 3.12 를 받아오고, 그 설치 위치를 `setup-uv` 는
`$RUNNER_TEMP/uv-python-dir` 로 잡는다 — 잡마다 새로 생기고 캐시되지 않는 디렉터리다.
그래서 venv 만 캐시하면 복원본의 심링크가 **dangling** 이 된다.

`setup-uv` 는 `UV_PYTHON=3.12` 를 세팅만 하고 미리 받아두지 않는다. 인터프리터는 `uv sync` 가
처음 돌 때 받아진다. 설치 스텝이 `if: cache-hit != 'true'` 로 건너뛰어지면 그 다운로드가 영영
안 일어나고 `.venv/bin/python: No such file or directory` → **exit 127** 이다.

24.04 에서는 `/usr/bin/python3.12` 가 있어 다운로드 자체가 없으므로 안 터진다. 그래서 이 파손은
**로컬에서도, 오늘의 main 에서도 재현되지 않는다** — 2026-10-19 러너 이관과 함께 도착한다.
실측(run 36395976186): cold 런은 Coverage Aggregate 하나만 죽지만, 같은 런을 rerun 해
캐시가 더워지면 **fast shard 8개가 전부** 죽는다.

세 축을 다 잠근다. 하나라도 되돌리면:
- 인터프리터를 캐시에서 빼면 → 26.04 에서 복원본이 dangling
- `cache-hit` 으로 설치를 가르면 → 못 쓰는 캐시에 exit 127 (원인 무관 방어선 소실)
- 설치 경로를 `setup-uv` 에 맡기면 → 그쪽이 경로를 바꾸는 날 조용히 재발
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION = REPO_ROOT / ".github/actions/setup-backend-env/action.yml"


def _steps() -> list[dict]:
    data = yaml.safe_load(ACTION.read_text())
    return data["runs"]["steps"]


def _step(name_fragment: str) -> dict:
    for step in _steps():
        if name_fragment in (step.get("name") or ""):
            return step
    raise AssertionError(f"setup-backend-env 에 '{name_fragment}' 스텝이 없다")


class TestVenvCacheIsSelfContained:
    """Gotcha-Test Pair: 인터프리터를 캐시 path 에서 빼면 FAIL."""

    def test_cache_covers_the_interpreter_too(self):
        """venv 와 인터프리터는 심링크로 묶여 있어 **같은 캐시 항목**이어야 한다.

        따로 캐시하면 한쪽만 복원된 순간 venv 가 통째로 못 쓰게 되고, 그 상태가
        `cache-hit=true` 로 보고된다.
        """
        paths = _step("Cache venv")["with"]["path"]
        entries = [p.strip() for p in str(paths).splitlines() if p.strip()]

        assert ".venv" in entries, f"venv 캐시가 .venv 를 안 담는다: {entries}"
        assert any("uv-python" in e for e in entries), (
            "venv 캐시에 uv 인터프리터 디렉터리가 없다 — 26.04 에서 복원된 "
            f".venv/bin/python 이 dangling 이 된다 (#1534).\n현재 path: {entries}"
        )

    def test_interpreter_dir_is_pinned_by_us_after_setup_uv(self):
        """설치 경로를 `setup-uv` 의 내부 선택에 맡기지 않는다.

        캐시 path 는 우리가 적은 리터럴이므로, 실제 설치 위치가 그와 다르면 캐시는
        **빈 디렉터리를 담고** 아무 신호 없이 원래 파손으로 돌아간다.
        """
        steps = _steps()
        names = [(s.get("name") or "") for s in steps]

        pin_idx = next(i for i, n in enumerate(names) if "Pin uv interpreter dir" in n)
        uv_idx = next(i for i, n in enumerate(names) if "Install uv" in n)
        cache_idx = next(i for i, n in enumerate(names) if "Cache venv" in n)

        assert uv_idx < pin_idx < cache_idx, (
            "UV_PYTHON_INSTALL_DIR 고정은 `Install uv` **뒤**(setup-uv 값을 덮어쓰려고) "
            "그리고 `Cache venv` **앞**(캐시가 그 경로를 담아야 하므로)에 와야 한다.\n"
            f"현재 순서: Install uv={uv_idx}, Pin={pin_idx}, Cache venv={cache_idx}"
        )

        pinned = steps[pin_idx]["run"]
        assert "UV_PYTHON_INSTALL_DIR" in pinned and "GITHUB_ENV" in pinned, (
            f"Pin 스텝이 UV_PYTHON_INSTALL_DIR 을 GITHUB_ENV 로 내보내지 않는다:\n{pinned}"
        )

        # 고정한 경로와 캐시가 담는 경로가 **같은 리터럴**이어야 한다.
        # 경로에 `${{ runner.temp }}` 가 들어가 공백을 품는다 — 닫는 따옴표까지 잡는다.
        pinned_path = re.search(r'UV_PYTHON_INSTALL_DIR=([^"]+)"', pinned)
        assert pinned_path, f"Pin 스텝에서 경로를 못 읽었다:\n{pinned}"
        cache_paths = str(_step("Cache venv")["with"]["path"])
        assert pinned_path.group(1) in cache_paths, (
            f"고정 경로 {pinned_path.group(1)!r} 가 venv 캐시 path 에 없다 — "
            f"캐시가 엉뚱한 디렉터리를 담는다.\n캐시 path: {cache_paths}"
        )


class TestInstallDoesNotTrustCacheHit:
    """Gotcha-Test Pair: 설치 조건을 `cache-hit` 으로 되돌리면 FAIL."""

    def test_install_is_gated_on_a_working_interpreter(self):
        """`cache-hit` 은 "복원됐다" 이지 "쓸 수 있다" 가 아니다.

        이게 원인-무관 방어선이다. 캐시가 어떤 이유로든 못 쓰게 되면 설치를 건너뛰고
        exit 127 로 죽는 대신 그냥 다시 깔아야 한다.
        """
        condition = _step("Install deps")["if"]
        assert "cache-hit" not in condition, (
            "`Install deps` 가 다시 cache-hit 으로 갈렸다 — 복원된 venv 가 못 쓰는 "
            f"상태여도 설치를 건너뛰어 exit 127 로 죽는다 (#1534).\n조건: {condition}"
        )

        check = _step("Check restored venv")
        step_id = check.get("id")
        assert step_id and step_id in condition, (
            f"`Install deps` 조건이 검사 스텝(id={step_id!r}) 결과를 안 본다: {condition}"
        )
        assert ".venv/bin/python" in check["run"], (
            "검사 스텝이 인터프리터를 **실행**해 보지 않는다 — `test -f` 류는 dangling "
            f"심링크를 통과시킨다.\n{check['run']}"
        )


class TestCacheKeyWasRotated:
    """인터프리터를 담기 전에 구운 캐시는 복원돼도 못 쓴다 — 키를 올려 새로 굽는다."""

    def test_key_and_restore_keys_share_the_version_marker(self):
        """`restore-keys` 가 구 prefix 로 남으면 낡은(인터프리터 없는) 캐시가 부분 복원된다."""
        with_ = _step("Cache venv")["with"]
        key, restore = with_["key"], str(with_["restore-keys"])

        marker = re.search(r"^venv-(v\d+)-", key)
        assert marker, f"venv 캐시 키에 버전 마커가 없다: {key}"
        assert f"venv-{marker.group(1)}-" in restore, (
            f"restore-keys 가 키의 버전 마커({marker.group(1)})와 안 맞는다 — "
            f"인터프리터 없는 구 캐시가 복원된다.\nkey={key}\nrestore-keys={restore}"
        )
