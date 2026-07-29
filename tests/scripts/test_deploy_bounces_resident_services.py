"""배포가 **상주 python 서비스를 전부 재기동**하는지 검증 (#940).

Gotcha-Test Pair:
`deploy_to_mini.sh` 는 오랫동안 `com.nuri-quant.scheduler` 만 bounce 했다. `api` 와
`discord-bot` 도 레포의 python 을 상주 실행하는데 어디서도 재기동되지 않아, 배포가
초록으로 끝난 뒤에도 구코드를 들고 있었다 (2026-07-29 실측: deploy 직후 api PID 가
06:03 기동분 — 그날 오후 머지한 `emit_event` 수정을 못 들고 있었다).

이 함정은 `docs/OPERATIONS.md` 복구표에 **이미 문서화돼 있었는데도 재발했다.** 문서로
두 번 실패했으므로 테스트로 잠근다. 새 상주 서비스를 추가하면 이 테스트가 먼저 걸린다.

판정 기준은 plist 자체에서 뽑는다 (하드코딩한 목록이 아니라):
  상주 = `StartInterval` / `StartCalendarInterval` 없음 (periodic 은 매 실행이 새 프로세스)
  python = `ProgramArguments` 가 `.venv/bin/python` 실행
"""

from __future__ import annotations

import plistlib
import re
from pathlib import Path

import pytest

LAUNCHD_DIR = Path("scripts/launchd")
DEPLOY_SCRIPT = Path("scripts/deploy/deploy_to_mini.sh")

# dashboard 는 상주지만 npm 빌드 산출물을 서빙한다 — 빌드가 바뀔 때만 바운스하는 게 맞고,
# 그 조건부 처리는 4단계에 이미 있다. python 판정에서 자연히 빠지지만 의도를 명시해 둔다.
_NOT_PYTHON_BY_DESIGN = {"com.nuri-quant.dashboard"}


def _plists() -> list[tuple[str, dict]]:
    out = []
    for path in sorted(LAUNCHD_DIR.glob("*.plist")):
        out.append((path.stem, plistlib.loads(path.read_bytes())))
    return out


def _is_resident(spec: dict) -> bool:
    """periodic 트리거가 없으면 상주 데몬."""
    return not ("StartInterval" in spec or "StartCalendarInterval" in spec)


def _runs_repo_python(spec: dict) -> bool:
    argv = " ".join(str(a) for a in spec.get("ProgramArguments", []))
    return ".venv/bin/python" in argv


def resident_python_labels() -> list[str]:
    return [label for label, spec in _plists() if _is_resident(spec) and _runs_repo_python(spec)]


def _declared_resident_services() -> set[str]:
    """`deploy_to_mini.sh` 가 선언한 bounce 대상 (`RESIDENT_SERVICES=(...)`)."""
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"RESIDENT_SERVICES=\(([^)]*)\)", script)
    return set(m.group(1).split()) if m else set()


class TestDeployBouncesEveryResidentPythonService:
    def test_sweep_is_not_blind(self):
        """캐너리 — plist 파싱이 조용히 빈 결과를 내면 아래 테스트가 공짜로 통과한다.

        (#910/#911 계열: 검사 미실행과 검사 통과가 구분 불가한 상태를 배제한다.)
        """
        labels = resident_python_labels()
        assert labels, "plist 스윕이 상주 python 서비스를 하나도 못 찾았다 — 스윕이 고장난 것"
        assert "com.nuri-quant.scheduler" in labels, "known 상주 서비스(scheduler)를 못 찾았다"

    @pytest.mark.parametrize("label", resident_python_labels())
    def test_deploy_script_bounces_it(self, label):
        """상주 python 서비스는 배포 때 재기동돼야 한다 — kickstart 또는 unload/load."""
        script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

        if label == "com.nuri-quant.scheduler":
            # plist 재설치가 필요해 kickstart 가 아니라 unload/load 경로를 쓴다 (#778/#856).
            assert "launchctl unload" in script and "launchctl load" in script, (
                "scheduler 의 unload/load 재기동 경로가 사라졌다"
            )
            return

        assert label in _declared_resident_services(), (
            f"{label} 은 상주 python 서비스인데 {DEPLOY_SCRIPT} 의 RESIDENT_SERVICES 에 없다.\n"
            "배포 후에도 구코드를 들고 도는 상태가 되고, 검증은 초록으로 끝난다 (#940)."
        )

    def test_declared_list_is_actually_bounced(self):
        """선언만 하고 안 부르는 상태를 배제 — 배열이 실제 kickstart 루프에 쓰여야 한다."""
        script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
        assert 'for RESIDENT in "${RESIDENT_SERVICES[@]}"' in script
        assert re.search(r"launchctl kickstart[^\n]*\$\{RESIDENT\}", script), (
            "RESIDENT_SERVICES 를 순회하지만 kickstart 하지 않는다"
        )

    def test_dashboard_stays_conditional(self):
        """dashboard 는 이 규칙 대상이 아니다 — 빌드 산출물 서빙이라 조건부가 맞다."""
        assert not any(label in _NOT_PYTHON_BY_DESIGN for label in resident_python_labels())


class TestDeployVerifiesApiLiveness:
    def test_final_step_checks_api_response_not_just_pid(self):
        """7단계 검증이 API **응답**을 본다 (#940).

        PID 존재만 보면 구코드로 도는 프로세스도 통과한다 — 실제로 그렇게 통과했다.
        """
        script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
        # 부분문자열 검사로는 부족하다 — 같은 URL 이 성공 메시지에도 들어 있어서, 실제
        # curl 을 지워도 통과했다 (이 테스트를 mutation 걸다 발견). **호출 자체**를 본다.
        assert re.search(r"curl[^\n]*127\.0\.0\.1:8001/api/health", script), (
            "7단계 검증에 API 라이브 curl 이 없다 — PID 존재만 보면 구코드로 도는 프로세스도 통과한다"
        )
