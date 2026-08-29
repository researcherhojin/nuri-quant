"""기계 밖 감시 dead-man heartbeat 잠금 (#1191 옵션 C).

세 반경을 나눠 잠근다:
- **role 게이트**: dev(MBP) 스케줄러가 heartbeat 를 push 하면 mini 의 침묵을
  가린다 — 게이트가 뚫리면 42h 급 공백이 **탐지 불가**로 돌아간다. 그래서 push
  경로 자체가 실행되지 않음을 spy 로 잠근다.
- **송신 동작**: mock 이 아니라 **실제 git** (tmp 레포 + 로컬 bare remote) 으로
  push 결과를 본다 — 빈-트리·무부모·신선한 committer 시각·force 갱신·익명 ident.
- **송신↔감시 배선**: 스케줄러 SCHEDULES 등재와, 워크플로가 같은 ref 이름·
  타당한 임계를 보는지. 한쪽만 rename 하면 여기서 깨진다.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from nuri.alerts.offbox_heartbeat import EMPTY_TREE, HEARTBEAT_REF, send_heartbeat

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "heartbeat-watch.yml"


@pytest.fixture()
def local_repo_with_bare_remote(tmp_path):
    """실제 push 를 받는 로컬 bare remote + 빈 트리 오브젝트가 준비된 작업 레포."""
    bare = tmp_path / "remote.git"
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    # 빈 트리 오브젝트를 명시적으로 심는다 — fresh 레포에는 loose object 로 없을
    # 수 있고, 프로덕션 레포에는 히스토리 덕에 항상 있다.
    subprocess.run(
        ["git", "hash-object", "-w", "-t", "tree", "--stdin"],
        cwd=work,
        input="",
        capture_output=True,
        text=True,
        check=True,
    )
    return work, bare


def test_dev_role_never_pushes(monkeypatch):
    """MBP 스케줄러의 heartbeat 가 mini 침묵을 가리면 안 된다 — no-op 을 잠근다.

    push 는커녕 커밋 생성조차 하지 않아야 한다: spy 가 subprocess 호출 0건을 본다.
    """
    monkeypatch.delenv("NURI_ROLE", raising=False)
    calls: list = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))

    assert send_heartbeat() is None
    assert calls == [], "role 게이트가 뚫렸다 — dev heartbeat 가 mini 의 침묵을 가린다"


class TestProductionSendsARealHeartbeat:
    def test_pushes_fresh_parentless_empty_tree_commit(self, monkeypatch, local_repo_with_bare_remote):
        monkeypatch.setenv("NURI_ROLE", "production")
        work, bare = local_repo_with_bare_remote

        sha = send_heartbeat(repo_root=work, remote_url=str(bare))

        assert sha, "production 인데 push 가 안 됐다"
        got = subprocess.run(
            ["git", "rev-parse", HEARTBEAT_REF],
            cwd=bare,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert got == sha, "remote ref 가 방금 만든 커밋을 가리키지 않는다"

        # 커밋 형태 잠금: 빈 트리 + 무부모 (브랜치가 커밋 1개로 고정되는 근거)
        tree = subprocess.run(
            ["git", "show", "-s", "--format=%T", sha], cwd=bare, capture_output=True, text=True, check=True
        ).stdout.strip()
        parents = subprocess.run(
            ["git", "show", "-s", "--format=%P", sha], cwd=bare, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert tree == EMPTY_TREE
        assert parents == "", "부모가 있으면 브랜치가 무한히 자란다"

    def test_second_send_replaces_the_ref(self, monkeypatch, local_repo_with_bare_remote):
        """무부모 커밋끼리는 non-fast-forward — force 경로가 실제로 동작해야 갱신된다.

        커밋 시각을 명시하는 이유: 같은 초 안의 두 heartbeat 는 내용·시각이 같아
        **같은 sha** 가 된다 (프로덕션은 10분 간격이라 항상 다르다). 시각을 갈라야
        non-ff force 경로가 실제로 밟힌다.
        """
        monkeypatch.setenv("NURI_ROLE", "production")
        work, bare = local_repo_with_bare_remote

        monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-08-29T10:00:00+09:00")
        first = send_heartbeat(repo_root=work, remote_url=str(bare))
        monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-08-29T10:10:00+09:00")
        second = send_heartbeat(repo_root=work, remote_url=str(bare))

        assert first and second and first != second, "커밋이 매번 새로 만들어져야 시각이 갱신된다"
        got = subprocess.run(
            ["git", "rev-parse", HEARTBEAT_REF], cwd=bare, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert got == second, "force 갱신 실패 — 두 번째 heartbeat 부터 전부 침묵으로 보인다"

    def test_ident_is_anonymous(self, monkeypatch, local_repo_with_bare_remote):
        """실 이메일이 heartbeat 커밋으로 새지 않는다 (author 익명화 방침)."""
        monkeypatch.setenv("NURI_ROLE", "production")
        work, bare = local_repo_with_bare_remote

        sha = send_heartbeat(repo_root=work, remote_url=str(bare))
        ident = subprocess.run(
            ["git", "show", "-s", "--format=%cn <%ce>", sha],
            cwd=bare,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert ident == "nuri-heartbeat <heartbeat@localhost>"

    def test_push_failure_returns_none_instead_of_raising(self, monkeypatch, local_repo_with_bare_remote, tmp_path):
        """실패 = 침묵 = 감시자 몫 — 스케줄러 wrapper 로 예외를 올리지 않는다."""
        monkeypatch.setenv("NURI_ROLE", "production")
        work, _ = local_repo_with_bare_remote

        assert send_heartbeat(repo_root=work, remote_url=str(tmp_path / "no-such-remote.git")) is None


class TestSenderAndWatcherAreWiredTogether:
    def test_scheduler_registers_the_job(self):
        from nuri.scheduler import SCHEDULES, _run_offbox_heartbeat

        entries = [s for s in SCHEDULES if s["name"] == "offbox_heartbeat"]
        assert len(entries) == 1, "SCHEDULES 미등재 — 함수만 있고 배선이 없으면 아무것도 안 돈다"
        assert entries[0]["func"] is _run_offbox_heartbeat
        assert entries[0]["cron"] == "*/10 * * * *"

    def test_watcher_watches_the_same_ref_with_a_sane_threshold(self):
        """송신 ref 이름과 감시 임계를 워크플로 본문에서 교차 잠금.

        - ref: 한쪽만 rename 하면 감시자는 영원히 'ref 없음' 침묵 알림만 낸다.
        - 임계: ping 간격(10분)보다 넉넉히 커야 배포 bounce/Actions cron 지연이
          가짜 알림이 되지 않고, 너무 크면 탐지가 늦다. 20 < threshold ≤ 120 로 잠근다.
        """
        text = WORKFLOW.read_text(encoding="utf-8")
        branch = HEARTBEAT_REF.removeprefix("refs/heads/")
        # substring 검사 금지 — `…-mini` 는 `…-mini-v2` 의 부분 문자열이라 rename 이
        # 통과한다 (뮤테이션 실측 MISS). API 호출부에서 ref 토큰을 뽑아 동치 비교.
        # 토큰은 %2F 인코딩 형태다 — 디코드 후 비교 (미인코딩 회귀도 여기서 잡힌다).
        m_ref = re.search(r'branches/([A-Za-z0-9%/_.-]+)"', text)
        assert m_ref, "워크플로에서 감시 대상 ref 를 찾을 수 없다"
        decoded = m_ref.group(1).replace("%2F", "/")
        assert decoded == branch, f"워크플로 ref {decoded!r} ≠ 송신 ref {branch!r}"
        assert "DISCORD_WEBHOOK_OPS" in text, "알림 채널 secret 참조가 사라졌다"

        m = re.search(r"THRESHOLD_MIN=(\d+)", text)
        assert m, "임계 상수를 찾을 수 없다"
        threshold = int(m.group(1))
        assert 20 < threshold <= 120, f"임계 {threshold}분 — ping 10분 대비 비상식적"
