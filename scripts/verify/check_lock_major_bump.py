#!/usr/bin/env python3
"""두 `uv.lock` 사이의 major 경계 이동을 잡는다 — dependabot 은 이걸 못 본다 (#1364).

## 왜 fetch-metadata 를 못 믿는가

dependabot 의 semver 분류는 **manifest requirement 의 변화**를 본다. `pyproject.toml` 이
`"numpy>=1.26.0"` 이라 2.5.2 도 제약을 만족하고 manifest 는 안 바뀐다 — numpy 는 애초에
"업데이트" 로 분류조차 되지 않아 `dependency-names` 에 이름이 나오지도 않는다.

PR #1355 는 그래서 `dependency-names=scipy` / `update-type=semver-minor` /
`group=python-data` 로 도착했고, `dependabot-auto-merge.yml` 이 "grouped minor update" 로
판정해 **무인 머지**했다. 실제 lock diff 는:

    llvmlite 0.46.0 -> 0.49.0 · numba 0.64.0 -> 0.67.0 · numpy 1.26.4 -> 2.5.2
    pykrx    1.2.4  -> 1.2.8  · scipy 1.17.1 -> 1.18.1

`numba` 와 `llvmlite` 는 `pyproject.toml` 에 **아예 없다**(transitive). manifest 를 보는
어떤 검사도 이 부류를 볼 수 없다 — lock 비교만이 본다. pip→uv 전환(#1352)이 연 축이다:
pip 은 `uv.lock` 을 쓰는 코드 경로가 없어 이 일이 불가능했다.

## 왜 TOML 파싱인가 — diff 가 아니라

`git show <sha> -- uv.lock` 의 diff 는 `-version = "1.26.4"` 라는 **이름 없는 줄**을 준다.
패키지 귀속은 hunk context 로만 복원되는데, 그게 되는 건 uv 가 `name` 을 `version` 바로
윗줄에 두기 때문이지 보장이 아니다. 두 파일을 통째로 파싱하면 귀속 단계 자체가 없다.
861 KB 를 `tomllib` 로 읽는 데 실측 0.05s 라 속도 논거도 없다.

## 실행 불가 ≠ 통과

파싱 실패 · 버전 해석 실패 · resolution-marker fork 는 전부 **차단**한다. "검사를 못
돌렸다" 를 "경계 없음" 으로 보고하는 것이 #910/#911(rc=127) · #953/#954(exit 0) 계열의
핵심 실패다. 오차단 비용은 dependabot PR 하나에 사람 클릭 한 번이고, 오통과 비용은
#1355 다.

## 아는 한계 — 이걸 덮는다고 착각하지 말 것

major 경계를 **안 넘는** 파손은 못 본다 (numpy 2.5→2.6 의 private API 제거 같은 것).
yanked wheel, 같은 버전의 아티팩트 교체도 못 본다. CalVer 패키지(`tzdata 2025.3`,
`pywin32 312`)는 major 판정 대상에서 제외된다 — 안 그러면 매년 오탐한다.
`frontend/package-lock.json` 은 같은 노출이 있으나 이 스크립트 범위 밖이다.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: PEP 440 의 release 부분만 뽑는다. pre/post/dev 접미사는 major 경계와 무관하므로 버린다
#: (`0.12.10b0` -> (0,12,10), `2026.1.post1` -> (2026,1)). 앞에 붙는 `1!` 은 epoch.
_RELEASE = re.compile(r"^(?:(\d+)!)?(\d+(?:\.\d+)*)")

#: 이 이상이면 연도(또는 빌드번호)지 semver major 가 아니다. 두 번째 성분까지 보는 것은
#: `astropy-iers-data 0.2026.3.30.0.54.34` 때문이다 — 없으면 매년 1월 1일에 0.x-minor 로
#: 오탐한다. 단일 성분(`pywin32 312`)도 같은 부류다.
_CALENDAR_FLOOR = 1000


class LockFormatError(RuntimeError):
    """lock 을 신뢰할 수 있는 {이름: 버전} 으로 못 줄인 경우 — 통과가 아니라 차단."""


def parse_lock(text: str) -> dict[str, str]:
    """registry 패키지만 {이름: 버전} 으로. editable/git/path 항목은 판정 대상이 아니다."""
    data = tomllib.loads(text)
    if data.get("version") != 1:
        raise LockFormatError(f"모르는 uv.lock 스키마 version={data.get('version')!r}")
    out: dict[str, str] = {}
    for pkg in data.get("package", []):
        # 루트(`source = {editable = "."}`)는 제외한다. 이름이 아니라 **source 로** 거른다 —
        # 리네임하거나 editable 멤버가 늘어도 조용히 다시 들어오지 않게. 루트를 판정하면
        # 레포 자체 버전 bump(0.1.0 -> 0.2.0)가 매번 major 로 잡힌다.
        if "registry" not in pkg.get("source", {}):
            continue
        name, version = pkg.get("name"), pkg.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise LockFormatError(f"name/version 이 없는 패키지 항목: {pkg.get('name')!r}")
        if name in out:
            # uv 의 universal resolution 은 `resolution-markers` 로 같은 이름을 여러 번
            # 쓸 수 있다. 현재 lock 은 0건이지만 헤더에 marker 가 이미 있어 한 의존성
            # 차이다. 생기면 단일 버전으로 못 줄인다 — 조용히 last-writer-wins 하지 말고
            # 차단하고 사람에게 넘긴다.
            raise LockFormatError(f"{name}: resolution-marker fork — 단일 버전으로 못 줄인다")
        out[name] = version
    if not out:
        raise LockFormatError("registry 패키지를 하나도 못 읽었다")
    return out


def release(version: str) -> tuple[int, tuple[int, ...]] | None:
    """`(epoch, release 성분)`. 해석 불가면 None (호출부가 차단한다)."""
    m = _RELEASE.match(version.strip())
    if not m:
        return None
    return int(m.group(1) or 0), tuple(int(x) for x in m.group(2).split("."))


def _is_calendar(rel: tuple[int, ...]) -> bool:
    return len(rel) == 1 or rel[0] >= _CALENDAR_FLOOR or rel[1] >= _CALENDAR_FLOOR


def crossing(base: str, head: str) -> str | None:
    """경계를 넘으면 사유 문자열, 아니면 None."""
    rb, rh = release(base), release(head)
    if rb is None or rh is None:
        return "unparseable version"
    if rb[0] != rh[0]:
        return "epoch change"
    b, h = rb[1], rh[1]
    cb, ch = _is_calendar(b), _is_calendar(h)
    if cb and ch:
        return None
    if cb != ch:
        return "versioning scheme change"
    if b[0] != h[0]:
        return "major"
    if b[0] == 0 and (b[1] if len(b) > 1 else 0) != (h[1] if len(h) > 1 else 0):
        # 0.x 관례: minor 가 breaking 이다. 이 절이 없으면 numba 0.64->0.67 과
        # llvmlite 0.46->0.49 (#1355 의 나머지 절반)가 통과한다. lock 의 24% 가 0.x 고
        # fastapi/uvicorn/httpx/vectorbt/ta-lib 가 전부 여기 있다.
        return "0.x minor (breaking by convention)"
    return None


def compare_locks(
    base: dict[str, str], head: dict[str, str]
) -> tuple[list[tuple[str, str, str, str]], list[tuple[str, str, str]], list[str], list[str]]:
    """(경계 이동, 통상 변경, 추가, 제거)."""
    crossings: list[tuple[str, str, str, str]] = []
    benign: list[tuple[str, str, str]] = []
    for name in sorted(base.keys() & head.keys()):
        if base[name] == head[name]:
            continue
        reason = crossing(base[name], head[name])
        if reason:
            crossings.append((name, base[name], head[name], reason))
        else:
            benign.append((name, base[name], head[name]))
    return crossings, benign, sorted(head.keys() - base.keys()), sorted(base.keys() - head.keys())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="uv.lock major-boundary gate (#1364)")
    parser.add_argument("--base", required=True, help="base 쪽 uv.lock 경로")
    parser.add_argument("--head", required=True, help="head 쪽 uv.lock 경로")
    args = parser.parse_args(argv)

    try:
        base = parse_lock(Path(args.base).read_text(encoding="utf-8"))
        head = parse_lock(Path(args.head).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, LockFormatError) as exc:
        print(f"✗ uv.lock 을 읽지 못했다 — '경계 없음' 이 아니라 '미확인' 이다: {exc}")
        return 1

    crossings, benign, added, removed = compare_locks(base, head)

    for name, before, after, reason in crossings[:30]:
        print(f"✗ lock bump crosses a major boundary: {name} {before} -> {after} ({reason})")
    for name, before, after in benign[:30]:
        print(f"  · {name} {before} -> {after}")
    # 추가/제거는 **차단하지 않는다** — 통상 patch bump 도 전이 의존성을 갈아치운다
    # (openbb 4.7.1->4.7.2 가 frozendict 를 제거했다). Surface 만 한다.
    if added:
        print(f"  + added ({len(added)}): {', '.join(added[:20])}")
    if removed:
        print(f"  - removed ({len(removed)}): {', '.join(removed[:20])}")

    if crossings:
        print(f"✗ {len(crossings)} boundary crossing(s) — auto-merge blocked, human review required")
        return 1
    print(f"✓ uv.lock: {len(benign)} version change(s), no major boundary crossed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
