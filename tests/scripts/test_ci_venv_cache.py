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

설치를 건너뛰는 조건은 **"정확 hit 이면서 인터프리터가 돈다"** 이고, 두 축은 서로 다른 것을
막는다. `cache-hit` 을 빼고 인터프리터 검사로 **교체**하면 새로운 파손이 생긴다: restore-keys
부분 복원은 **구 lock** 의 venv 를 되살리는데 그 인터프리터는 멀쩡히 돌아 설치가 생략되고,
샤드가 `uv run` 이 아니라 `.venv/bin/python` 을 직접 쓰므로(main-ci-cd.yml:724 · :790) 아무도
안 되돌린다 → **구 의존성으로 새 소스를 테스트**한다. uv.lock 이 바뀌는 PR = dependabot 전부라
빈도가 높고, 26.04 와 달리 **오늘의 24.04 에서도** 난다.

네 축을 잠근다. 하나라도 되돌리면:
- 인터프리터를 캐시에서 빼면 → 26.04 에서 복원본이 dangling
- 설치 조건에서 `cache-hit` 을 빼면 → 부분 복원에서 구 lock 으로 테스트
- 설치 조건에서 인터프리터 검사를 빼면 → 못 쓰는 캐시에 exit 127
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


class TestInstallGate:
    """Gotcha-Test Pair: 두 조건 중 **하나라도** 빼면 FAIL.

    계약은 "cache-hit 을 쓰지 마라" 가 아니라 **"정확 hit 이면서 인터프리터가 돌 때만
    설치를 건너뛴다"** 이다. 두 조건은 서로 다른 파손을 막고, 어느 쪽도 다른 쪽을
    대신하지 못한다.
    """

    def test_skip_requires_an_exact_hit(self):
        """restore-keys 부분 복원이면 복원된 venv 는 **구 lock** 의 것이다.

        인터프리터는 멀쩡히 돌아 `usable=true` 가 되므로, `cache-hit` 축이 없으면
        sync 가 생략되고 구 의존성으로 새 소스를 테스트한다. 샤드는 `uv run` 이 아니라
        `.venv/bin/python` 을 직접 실행하므로 뒤에서 되돌려주는 것도 없다.
        uv.lock 이 바뀌는 PR = dependabot 전부라 빈도가 높다.
        """
        condition = _step("Install deps")["if"]
        assert "cache-venv" in condition and "cache-hit" in condition, (
            "`Install deps` 가 exact-hit 여부를 안 본다 — restore-keys 부분 복원에서 "
            f"sync 가 생략되고 **구 lock 의 의존성**으로 테스트가 돈다.\n조건: {condition}"
        )

    def test_skip_requires_a_working_interpreter(self):
        """`cache-hit` 은 "복원됐다" 이지 "쓸 수 있다" 가 아니다 (#1534).

        26.04 에서 복원된 venv 는 심링크가 끊겨 있는데도 `cache-hit=true` 로 보고된다.
        원인이 무엇이든 `exit 127` 대신 재설치로 떨어지는 방어선.
        """
        condition = _step("Install deps")["if"]
        check = _step("Check restored venv")
        step_id = check.get("id")
        assert step_id and step_id in condition, (
            f"`Install deps` 조건이 검사 스텝(id={step_id!r}) 결과를 안 본다 — 못 쓰는 "
            f"캐시에 exit 127 로 죽는다 (#1534).\n조건: {condition}"
        )
        assert ".venv/bin/python" in check["run"], (
            "검사 스텝이 인터프리터를 **실행**해 보지 않는다 — `test -f` 류는 dangling "
            f"심링크를 통과시킨다.\n{check['run']}"
        )

    def test_the_two_conditions_are_or_ed_not_and_ed(self):
        """AND 면 둘 다 어긋나야 설치된다 — 각각이 단독으로 파손을 잡아야 한다."""
        condition = _step("Install deps")["if"]
        assert "||" in condition and "&&" not in condition, (
            "두 조건은 OR 여야 한다. AND 면 한쪽만 어긋난 경우(부분 복원인데 "
            f"인터프리터는 멀쩡 / 정확 hit 인데 인터프리터가 끊김)를 놓친다.\n조건: {condition}"
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
