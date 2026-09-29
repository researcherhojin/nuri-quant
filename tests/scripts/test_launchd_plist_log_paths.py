"""`UserName` 이 root 가 아닌 plist 의 로그 경로가 그 사용자가 쓸 수 있는 곳인지 검사한다 (#1574).

## 왜 형태로 막는가

launchd 는 `Standard{Out,Error}Path` 를 **프로그램 실행 전에** 그 job 의 사용자로 연다.
못 열면 프로그램을 아예 돌리지 않고 `exit 78 (EX_CONFIG)` 로 끝낸다 — 그리고 로그 파일이
생기지 않으므로 **증거가 남지 않는다.** `install_daemons.sh` 는 `✅ installed` 를 찍고
`launchctl` 등록도 성공하므로 설치 로그로도 안 보인다.

실측(#1574, 2026-09-29 mini): `machine-alive` 가 `UserName=<계정>` 인데 로그 경로가
`/var/log`(root:wheel drwxr-xr-x) 였다. `runs=1 / last exit code=78 / state=not running`,
그 사이 `refs/nuri/machine-mini` 는 한 번도 갱신되지 않았다. **감시자가 설치됐는데 감시를
하지 않는 상태**였고, 그걸 알아낸 건 설치 성공 메시지가 아니라 `launchctl print` 였다.

시스템 도메인 plist 는 `UserName` 을 두는 것이 정상이다(root 면 `$HOME=/var/root` 라 deploy
key 와 레포를 못 찾는다 — plist 주석 참조). 그래서 "root 로 돌려라" 가 아니라 "로그를 그
사용자 홈 아래 둬라" 가 답이다.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLIST_DIRS = (REPO_ROOT / "scripts" / "launchd", REPO_ROOT / "scripts" / "launchd" / "system")

# 설치 시 `/Users/USER` → 실제 홈으로 치환된다 (`install_crons.sh` / `install_daemons.sh`).
USER_HOME_PREFIX = "/Users/USER/"
# 그 사용자가 쓸 수 없는 것으로 알려진 곳. 루트 소유 시스템 디렉터리.
ROOT_ONLY_PREFIXES = ("/var/log", "/var/root", "/Library/Logs", "/usr/", "/etc/", "/private/var/log")


def _plists() -> list[Path]:
    out: list[Path] = []
    for d in PLIST_DIRS:
        out.extend(sorted(p for p in d.glob("com.nuri-quant.*.plist") if p.is_file()))
    return out


def _load(path: Path) -> dict:
    with path.open("rb") as fh:
        return plistlib.load(fh)


def _log_paths(data: dict) -> list[tuple[str, str]]:
    return [(k, data[k]) for k in ("StandardOutPath", "StandardErrorPath") if k in data]


class TestLogPathsAreWritableByTheJobUser:
    @pytest.mark.parametrize("plist", _plists(), ids=lambda p: p.name)
    def test_a_non_root_job_logs_under_its_own_home(self, plist):
        data = _load(plist)
        user = data.get("UserName")
        if user in (None, "root"):
            return  # root 로 도는 job 은 /var/log 를 써도 된다
        for key, value in _log_paths(data):
            assert value.startswith(USER_HOME_PREFIX), (
                f"{plist.name}: {key}={value!r} 인데 UserName={user!r} 다 — launchd 가 리다이렉트를 "
                f"못 열면 프로그램을 돌리지 않고 exit 78(EX_CONFIG)로 조용히 끝낸다. "
                f"`{USER_HOME_PREFIX}...` 아래로 둘 것 (#1574)."
            )

    @pytest.mark.parametrize("plist", _plists(), ids=lambda p: p.name)
    def test_no_job_logs_into_a_root_only_directory(self, plist):
        """root 로 도는 job 이라도 실수로 `/var/root` 같은 곳을 쓰면 운영자가 못 읽는다."""
        data = _load(plist)
        if data.get("UserName") in (None, "root"):
            return
        for key, value in _log_paths(data):
            bad = [p for p in ROOT_ONLY_PREFIXES if value.startswith(p)]
            assert not bad, f"{plist.name}: {key}={value!r} 가 root 전용 경로 {bad} 아래다 (#1574)."

    def test_the_scan_actually_sees_the_plists(self):
        """가드의 가드 — glob 이 비면 위 두 테스트가 공허하게 통과한다."""
        names = {p.name for p in _plists()}
        assert "com.nuri-quant.machine-alive.plist" in names, names
        assert len(names) >= 8, names

    @pytest.mark.parametrize("plist", _plists(), ids=lambda p: p.name)
    def test_every_plist_parses(self, plist):
        """깨진 plist 는 launchd 가 로드 자체를 거부한다 — 그것도 조용하다."""
        assert _load(plist).get("Label"), f"{plist.name}: Label 이 없다"
