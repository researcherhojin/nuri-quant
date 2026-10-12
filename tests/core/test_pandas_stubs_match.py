"""pandas-stubs 는 설치된 pandas 와 major.minor 가 같아야 한다.

pyright 는 pandas 의 타입을 이 stub 으로 읽는다. stub 이 없던 동안 pyright 는 `DatetimeIndex[i]` 를
`Index` 로 보는 식의 오탐을 냈다 — 2026-10-12 실측으로 전체 오류 174 건 중 145 건이 그것이었다.
버전이 어긋나면 같은 일이 다른 모양으로 돌아온다: 새 pandas 에 생긴 API 를 없다고 하거나,
사라진 API 를 있다고 한다. dependabot 의 `python-data` 그룹(`pandas*`)은 둘을 한 PR 로 올리지만,
한쪽만 움직이는 bump 는 이 테스트가 잡는다.
"""

from __future__ import annotations

from importlib.metadata import version


def _major_minor(v: str) -> tuple[int, int]:
    major, minor = v.split(".")[:2]
    return int(major), int(minor)


def test_pandas_stubs_track_the_installed_pandas_minor():
    pandas_v, stubs_v = version("pandas"), version("pandas-stubs")
    assert _major_minor(stubs_v) == _major_minor(pandas_v), (
        f"pandas {pandas_v} 와 pandas-stubs {stubs_v} 의 major.minor 가 다르다 — "
        "pyproject.toml 의 pandas-stubs 범위를 pandas 에 맞춰 올릴 것"
    )
