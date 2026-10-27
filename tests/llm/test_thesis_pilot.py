"""thesis 파일럿 러너 (#1964)."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from nuri.core.db import get_db, init_db
from nuri.core.timezone import KST
from nuri.llm import local_client as lc
from nuri.llm import thesis_freeze as tf
from nuri.llm import thesis_pilot as tp

REPO = Path(__file__).resolve().parents[2]
# 수요일 아침 KST — 전날(화) 미국 세션 뒤, 미장 마감 브리프(16:30 ET)에서 한참 지난 시각
NOW = datetime(2026, 11, 4, 10, 0, tzinfo=KST)
COHORT = NOW.date()
UNIVERSE = [f"T{i:02d}" for i in range(30)]
PILOT = tp.Pilot("pilot-x", 5, ("A", "B"), 75)


def git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def world(tmp_path, monkeypatch):
    """작은 저장소 — 파일럿 · 유니버스 · 동결 · 런타임 설정과 DB. 러너는 운영 역할에서만 원장에 쓴다."""
    monkeypatch.setenv("NURI_ROLE", "production")
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "data").mkdir()
    shutil.copy(REPO / lc.CONFIG_PATH, repo / lc.CONFIG_PATH)
    (repo / tp.UNIVERSE_PATH).write_text(
        yaml.safe_dump(
            {
                "us_core": {"tickers": UNIVERSE[:10]},
                "us_sp500_extended": {"tickers": UNIVERSE[10:]},
                "kr_kospi200": {"tickers": ["005930.KS"]},
            }
        )
    )
    (repo / tp.PILOT_PATH).write_text(
        yaml.safe_dump({"experiment": "pilot-x", "tickers_per_night": 5, "arms": ["A", "B"], "brief_quiet_minutes": 75})
    )
    hashes = tf.current_hashes(lc.load_config(repo / lc.CONFIG_PATH))
    freeze(repo, "pilot-x", date(2026, 11, 2), date(2026, 11, 27), hashes)
    (repo / ".gitignore").write_text("data/\n")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    db = repo / "data" / "portfolio.db"
    init_db(db)
    return repo, db


def freeze(repo, experiment, start, end, arms):
    doc = {"freezes": [{"experiment": experiment, "start": start, "end": end, "arms": dict(arms)}]}
    (repo / tf.FREEZE_PATH).write_text(yaml.safe_dump(doc))


def pre(world, pilot=PILOT, now=NOW):
    repo, db = world
    return tp.preflight(pilot, now, freeze_path=repo / tf.FREEZE_PATH, config_path=repo / lc.CONFIG_PATH, db_path=db)


class TestConfig:
    def test_the_tracked_config_ships_disabled(self):
        assert tp.load_pilot(REPO / tp.PILOT_PATH) is None

    def test_a_valid_config_loads(self, world):
        assert tp.load_pilot(world[0] / tp.PILOT_PATH) == PILOT

    @pytest.mark.parametrize(
        "over",
        [
            {"experiment": " "},
            {"tickers_per_night": 1},
            {"tickers_per_night": "10"},
            {"arms": ["A", "C"]},
            {"arms": ["A", "A"]},
            {"arms": []},
            {"arms": ["A", "S"]},
            {"brief_quiet_minutes": -1},
        ],
    )
    def test_a_malformed_config_is_refused(self, tmp_path, over):
        doc = {"experiment": "p", "tickers_per_night": 5, "arms": ["A", "B"], "brief_quiet_minutes": 75} | over
        p = tmp_path / "p.yaml"
        p.write_text(yaml.safe_dump(doc))
        with pytest.raises(ValueError):
            tp.load_pilot(p)


class TestDraw:
    def test_the_us_universe_excludes_korea(self, world):
        assert tp.us_universe(world[0] / tp.UNIVERSE_PATH) == UNIVERSE

    def test_the_same_inputs_draw_the_same_tickers_in_the_same_order(self):
        a = tp.draw("pilot-x", COHORT, UNIVERSE, 5)
        assert a == tp.draw("pilot-x", COHORT, UNIVERSE, 5)
        assert len(set(a["tickers"])) == 5 and set(a["tickers"]) <= set(UNIVERSE)

    @pytest.mark.parametrize(
        ("experiment", "cohort", "universe"),
        [("pilot-y", COHORT, UNIVERSE), ("pilot-x", date(2026, 11, 5), UNIVERSE), ("pilot-x", COHORT, UNIVERSE[1:])],
    )
    def test_a_different_experiment_cohort_or_universe_draws_differently(self, experiment, cohort, universe):
        base = tp.draw("pilot-x", COHORT, UNIVERSE, 5)
        other = tp.draw(experiment, cohort, universe, 5)
        assert other["seed"] != base["seed"] and other["tickers"] != base["tickers"]

    def test_the_seed_is_not_python_hash(self):
        """`hash()` 는 프로세스마다 달라진다 — 다른 인터프리터에서도 같은 추첨이어야 한다."""
        code = (
            "from datetime import date; from nuri.llm import thesis_pilot as tp; "
            f"print(tp.draw('pilot-x', date(2026, 11, 4), {UNIVERSE!r}, 5)['tickers'])"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO,
            env={**os.environ, "PYTHONHASHSEED": "123"},
        )
        assert out.stdout.strip() == str(tp.draw("pilot-x", COHORT, UNIVERSE, 5)["tickers"])

    def test_more_tickers_than_the_universe_is_refused(self):
        with pytest.raises(ValueError, match="cannot draw"):
            tp.draw("pilot-x", COHORT, UNIVERSE[:3], 5)


class TestCalendar:
    @pytest.mark.parametrize(
        ("kst_day", "expected"),
        [
            (date(2026, 11, 4), True),  # 화요일 세션 뒤
            (date(2026, 11, 3), True),  # 월요일 세션 뒤
            (date(2026, 11, 2), False),  # 일요일 뒤
            (date(2026, 11, 1), False),  # 토요일 뒤
            (date(2026, 11, 27), False),  # 추수감사절(11-26) 뒤
        ],
    )
    def test_nights_follow_nyse_sessions_only(self, kst_day, expected):
        assert tp.after_session(kst_day) is expected

    @pytest.mark.parametrize(
        ("now", "busy"),
        [
            (datetime(2026, 7, 1, 5, 30, tzinfo=KST), True),  # EDT 16:30
            (datetime(2026, 7, 1, 6, 45, tzinfo=KST), True),  # EDT 17:45, 75분 안
            (datetime(2026, 7, 1, 7, 0, tzinfo=KST), False),
            (datetime(2026, 12, 1, 6, 30, tzinfo=KST), True),  # EST 16:30
            (datetime(2026, 12, 1, 6, 15, tzinfo=KST), True),  # EST 16:15, 15분 전 경계
            (datetime(2026, 12, 1, 6, 10, tzinfo=KST), False),
        ],
    )
    def test_the_brief_window_follows_new_york_time(self, now, busy):
        assert tp.brief_busy(now, 75) is busy


class TestPreflight:
    def test_a_frozen_session_night_passes(self, world):
        assert pre(world) is None

    def test_every_arm_that_runs_must_be_frozen(self, world):
        """A 만 얼린 창으로 A · B 를 돌리면 B 가 움직여도 못 막는다 (Codex 리뷰)."""
        hashes = tf.current_hashes(lc.load_config(world[0] / lc.CONFIG_PATH))
        freeze(world[0], "pilot-x", date(2026, 11, 2), date(2026, 11, 27), {"A": hashes["A"]})
        assert pre(world) == "not_frozen"
        assert pre(world, pilot=tp.Pilot("pilot-x", 5, ("A",), 75)) is None

    def test_a_night_without_a_session_is_skipped(self, world):
        assert pre(world, now=datetime(2026, 11, 2, 10, 0, tzinfo=KST)) == "no_session"

    def test_a_moved_definition_inside_the_window_is_refused(self, world):
        freeze(world[0], "pilot-x", date(2026, 11, 2), date(2026, 11, 27), {"A": "0" * 64})
        assert pre(world) == "freeze_violation"

    @pytest.mark.parametrize(
        ("experiment", "start", "end"),
        [("other", date(2026, 11, 2), date(2026, 11, 27)), ("pilot-x", date(2026, 11, 5), date(2026, 11, 27))],
    )
    def test_no_window_for_this_experiment_today_is_refused(self, world, experiment, start, end):
        freeze(
            world[0], experiment, start, end, {"A": tf.current_hashes(lc.load_config(world[0] / lc.CONFIG_PATH))["A"]}
        )
        assert pre(world) == "not_frozen"

    def test_the_brief_window_is_refused(self, world):
        assert pre(world, now=datetime(2026, 11, 4, 6, 40, tzinfo=KST)) == "ollama_busy"

    def test_a_second_batch_on_the_same_cohort_is_refused(self, world):
        _, db = world
        started = datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc).isoformat()  # KST 10:00 같은 날
        with get_db(db) as conn:
            conn.execute(
                "INSERT INTO thesis_batches (batch_id, experiment, started_at, canary_start, status) "
                "VALUES ('b', 'pilot-x', ?, 'c', 'ok')",
                (started,),
            )
        assert pre(world) == "already_ran"
        assert pre(world, pilot=tp.Pilot("pilot-y", 5, ("A", "B"), 75)) == "not_frozen"


FAKE = textwrap.dedent(
    """
    import json, os, subprocess, sys
    rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    with open(os.path.join("data", "calls.jsonl"), "a") as f:
        f.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(), "rev": rev}) + "\\n")
    sys.exit(int(sys.argv[1]))
    """
)


class TestRunNight:
    def _fake(self, monkeypatch, rcs=(0, 0), tree_hashes=None, freeze_rc=0):
        """배치 · 정산 명령과, 고정 트리 안의 지문 계산(그 트리에는 nuri 가 없다)을 가짜로."""

        def fake_commands(pilot, tickers, python, db_path=None):
            db = [str(db_path)] if db_path is not None else []
            return [
                [python, "-c", FAKE, str(rc), name, ",".join(tickers), *db] for rc, name in zip(rcs, ("arm", "memory"))
            ]

        hashes = tree_hashes or tf.current_hashes(lc.load_config(REPO / lc.CONFIG_PATH))
        code = f"import sys; print({json.dumps(hashes)!r}); sys.exit({freeze_rc})"
        monkeypatch.setattr(tp, "commands", fake_commands)
        monkeypatch.setattr(tp, "freeze_command", lambda python: [python, "-c", code])

    def test_batch_then_settlement_run_in_order_from_a_tree_pinned_to_head(self, world, monkeypatch):
        repo, db = world
        self._fake(monkeypatch)
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        assert tp.run_night(PILOT, NOW, repo=repo, python=sys.executable, db_path=db) == 0
        calls = [json.loads(x) for x in (repo / "data" / "calls.jsonl").read_text().splitlines()]
        assert [c["argv"][1] for c in calls] == ["arm", "memory"]
        tree = repo / tp.WORK_DIR / "wt-pilot-x-2026-11-04"
        assert {c["cwd"] for c in calls} == {str(tree.resolve())} and {c["rev"] for c in calls} == {head}
        assert not tree.exists(), "고정 트리를 지우지 않았다"
        record = json.loads((repo / tp.WORK_DIR / "draws" / "pilot-x-2026-11-04.json").read_text())
        assert record == tp.draw("pilot-x", COHORT, UNIVERSE, 5)
        assert calls[0]["argv"][2] == ",".join(record["tickers"])
        assert {c["argv"][3] for c in calls} == {str(db)}, "자식이 사전 점검과 다른 DB 를 쓴다"

    def test_a_relative_database_path_means_the_same_file_in_the_children(self, world, monkeypatch):
        repo, db = world
        self._fake(monkeypatch)
        monkeypatch.chdir(repo)
        assert tp.run_night(PILOT, NOW, repo=repo, python=sys.executable, db_path=Path("data/portfolio.db")) == 0
        calls = [json.loads(x) for x in (repo / "data" / "calls.jsonl").read_text().splitlines()]
        assert {c["argv"][3] for c in calls} == {str(db.resolve())}

    @pytest.mark.parametrize("rcs", [(3, 0), (0, 3)])
    def test_the_worst_exit_code_is_returned_and_settlement_still_runs(self, world, monkeypatch, rcs):
        repo, db = world
        self._fake(monkeypatch, rcs=rcs)
        assert tp.run_night(PILOT, NOW, repo=repo, python=sys.executable, db_path=db) == 3
        assert len((repo / "data" / "calls.jsonl").read_text().splitlines()) == 2

    @pytest.mark.parametrize(("over", "freeze_rc"), [({"B": "0" * 64}, 0), ({}, 1)])
    def test_a_definition_that_moved_before_the_tree_was_pinned_is_refused(self, world, monkeypatch, over, freeze_rc):
        """사전 점검 뒤 · 트리 생성 전에 배포가 끼면 트리의 지문이 다르다 — 그 트리로는 아무것도 돌리지 않는다."""
        repo, db = world
        moved = tf.current_hashes(lc.load_config(REPO / lc.CONFIG_PATH)) | over
        self._fake(monkeypatch, tree_hashes=moved, freeze_rc=freeze_rc)
        assert tp.run_night(PILOT, NOW, repo=repo, python=sys.executable, db_path=db) == 5
        assert not (repo / "data" / "calls.jsonl").exists()
        assert not (repo / tp.WORK_DIR / "wt-pilot-x-2026-11-04").exists()

    def test_a_signal_killed_batch_is_a_failure_even_when_settlement_succeeds(self, world, monkeypatch):
        repo, db = world
        monkeypatch.setattr(
            tp,
            "commands",
            lambda pilot, tickers, python, db_path=None: [
                [python, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"],
                [python, "-c", "pass"],
            ],
        )
        self_hashes = tf.current_hashes(lc.load_config(REPO / lc.CONFIG_PATH))
        monkeypatch.setattr(tp, "freeze_command", lambda python: [python, "-c", f"print({json.dumps(self_hashes)!r})"])
        assert tp.run_night(PILOT, NOW, repo=repo, python=sys.executable, db_path=db) == 128 + signal.SIGTERM

    def test_the_lock_outlives_a_killed_runner_while_its_batch_runs(self, world):
        """러너가 먼저 죽어도 배치 자식이 잠금을 쥔다 — 다음 실행이 트리를 지우고 두 번째 배치를 띄우지 못한다."""
        repo, db = world
        started, lock_path = repo / "data" / "started", repo / tp.WORK_DIR / "pilot-x.lock"
        hashes = tf.current_hashes(lc.load_config(REPO / lc.CONFIG_PATH))
        script = textwrap.dedent(
            f"""
            import sys, json
            from datetime import datetime
            from pathlib import Path
            from nuri.core.timezone import KST
            from nuri.llm import thesis_pilot as tp
            batch = "import time; open({str(started)!r}, 'w').close(); time.sleep(3)"
            tp.commands = lambda pilot, tickers, python, db_path=None: [[python, "-c", batch], [python, "-c", "pass"]]
            tp.freeze_command = lambda python: [python, "-c", "print(" + repr(json.dumps({hashes!r})) + ")"]
            pilot = tp.Pilot("pilot-x", 5, ("A", "B"), 75)
            now = datetime(2026, 11, 4, 10, 0, tzinfo=KST)
            tp.run_night(pilot, now, repo=Path({str(repo)!r}), python=sys.executable, db_path=Path({str(db)!r}))
            """
        )
        runner = subprocess.Popen([sys.executable, "-c", script], cwd=REPO)
        try:
            for _ in range(200):
                if started.exists():
                    break
                time.sleep(0.05)
            assert started.exists(), "배치가 시작하지 않았다"
            runner.kill()  # 러너만 죽는다 — 배치 자식은 그대로
            runner.wait(timeout=5)
            with lock_path.open("w") as f, pytest.raises(BlockingIOError):
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            if runner.poll() is None:
                runner.kill()

    def test_the_real_freeze_command_runs_the_guard_module(self):
        assert tp.freeze_command("py") == ["py", "-m", "nuri.llm.thesis_freeze"]

    def test_a_stale_tree_from_a_crashed_night_is_replaced(self, world, monkeypatch):
        repo, db = world
        self._fake(monkeypatch)
        stale = repo / tp.WORK_DIR / "wt-pilot-x-2026-11-04"
        stale.mkdir(parents=True)
        (stale / "leftover").write_text("x")
        assert tp.run_night(PILOT, NOW, repo=repo, python=sys.executable, db_path=db) == 0

    def test_a_concurrent_night_is_refused_by_the_lock(self, world, monkeypatch):
        repo, db = world
        self._fake(monkeypatch)
        (repo / tp.WORK_DIR).mkdir(parents=True)
        with (repo / tp.WORK_DIR / "pilot-x.lock").open("w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            assert tp.run_night(PILOT, NOW, repo=repo, python=sys.executable, db_path=db) == 4
        assert not (repo / "data" / "calls.jsonl").exists()

    @pytest.mark.parametrize(
        ("now", "rc"), [(datetime(2026, 11, 2, 10, 0, tzinfo=KST), 0), (datetime(2026, 11, 4, 6, 40, tzinfo=KST), 5)]
    )
    def test_a_refused_night_runs_nothing(self, world, monkeypatch, now, rc):
        repo, db = world
        self._fake(monkeypatch)
        assert tp.run_night(PILOT, now, repo=repo, python=sys.executable, db_path=db) == rc
        assert not (repo / "data" / "calls.jsonl").exists()

    def test_the_real_commands_forward_the_database(self):
        cmds = tp.commands(PILOT, ["T01"], "py", db_path=Path("/x/p.db"))
        assert all(c[-2:] == ["--db", "/x/p.db"] for c in cmds)

    def test_the_real_commands_score_and_then_settle(self):
        cmds = tp.commands(PILOT, ["T01", "T02"], "py")
        assert cmds == [
            [
                "py",
                "-m",
                "nuri.llm.thesis_arm",
                "--tickers",
                "T01,T02",
                "--arms",
                "A,B",
                "--scored",
                "--experiment",
                "pilot-x",
            ],
            ["py", "-m", "nuri.llm.thesis_memory"],
        ]


class TestDetach:
    def test_launch_returns_at_once_with_a_new_session_and_a_log(self, tmp_path):
        p = tp.launch([sys.executable, "-c", "print('hello')"], tmp_path / "logs" / "x.log", tmp_path)
        assert os.getpgid(p.pid) == p.pid  # 새 세션의 리더
        assert p.wait(timeout=10) == 0
        assert (tmp_path / "logs" / "x.log").read_text().strip() == "hello"

    def test_the_batch_survives_its_parent_process_group_being_killed(self, tmp_path):
        """launchd 는 job 이 죽을 때 같은 프로세스 그룹을 정리한다 — 스케줄러 재기동을 흉내 내 그룹을 죽인다."""
        done = tmp_path / "done"
        child = [sys.executable, "-c", f"import time; time.sleep(1.5); open({str(done)!r}, 'w').write('ok')"]
        parent_code = (
            "import sys, time; from pathlib import Path; from nuri.llm import thesis_pilot as tp; "
            f"p = tp.launch({child!r}, Path({str(tmp_path / 'log')!r}), Path({str(tmp_path)!r})); "
            f"Path({str(tmp_path / 'pid')!r}).write_text(str(p.pid)); time.sleep(30)"
        )
        parent = subprocess.Popen([sys.executable, "-c", parent_code], cwd=REPO, start_new_session=True)
        try:
            for _ in range(100):
                if (tmp_path / "pid").exists():
                    break
                time.sleep(0.05)
            child_pid = int((tmp_path / "pid").read_text())
            assert os.getpgid(child_pid) != os.getpgid(parent.pid)
            os.killpg(parent.pid, signal.SIGTERM)  # 스케줄러와 그 그룹이 죽는다
            parent.wait(timeout=5)
            for _ in range(100):
                if done.exists():
                    break
                time.sleep(0.05)
            assert done.read_text() == "ok", "부모 그룹과 함께 배치가 죽었다"
        finally:
            if parent.poll() is None:
                parent.kill()


class TestEntryPoints:
    def test_launch_does_nothing_while_disabled(self, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / tp.PILOT_PATH).write_text("experiment: null\n")
        assert tp.launch_night(tmp_path) is None

    def test_launch_starts_the_run_command_detached(self, world, monkeypatch):
        repo, _ = world
        seen = {}

        class P:
            pid = 4242

        def fake_launch(argv, log, cwd):
            seen.update(argv=argv, log=log, cwd=cwd)
            return P()

        monkeypatch.setattr(tp, "launch", fake_launch)
        assert tp.launch_night(repo, python="py") == 4242
        assert seen["argv"] == ["py", "-m", "nuri.llm.thesis_pilot", "run"] and seen["cwd"] == repo
        assert seen["log"].parent == repo / "data" / "logs"

    def test_the_cli_reports_disabled(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "config").mkdir()
        (tmp_path / tp.PILOT_PATH).write_text("experiment: null\n")
        monkeypatch.chdir(tmp_path)
        assert tp.main(["launch"]) == 0 and tp.main(["run"]) == 0
        assert capsys.readouterr().out.split() == ["disabled", "disabled"]

    def test_the_cli_runs_an_enabled_night(self, world, monkeypatch, capsys):
        repo, _ = world
        monkeypatch.chdir(repo)
        seen = {}
        monkeypatch.setattr(tp, "run_night", lambda pilot, now, repo, python: seen.update(pilot=pilot) or 7)
        monkeypatch.setattr(tp, "launch_night", lambda repo: 99)
        assert tp.main(["run"]) == 7 and seen["pilot"] == PILOT
        assert tp.main(["launch"]) == 0 and "launched 99" in capsys.readouterr().out


def night(db, cohort="2026-11-04"):
    rows = [dict(r) for r in _query("SELECT * FROM thesis_pilot_nights WHERE cohort_date = ?", (cohort,), db)]
    return rows[0] if rows else None


def night_row(db, cohort="2026-11-04") -> dict:
    n = night(db, cohort)
    assert n is not None, "밤 기록이 없다"
    return n


def _query(sql, params, db):
    from nuri.core.db import query

    return query(sql, params, db_path=db)


class TestNightRecords:
    """밤마다의 결말이 원장에 남는다 — 경보 · 보고가 읽는다 (#1998)."""

    def _fake(self, monkeypatch, rcs=(0, 0)):
        TestRunNight()._fake(monkeypatch, rcs=rcs)

    def test_a_ran_night_records_the_draw_the_exit_and_memory_samples(self, world, monkeypatch):
        repo, db = world
        self._fake(monkeypatch)
        monkeypatch.setattr(tp, "memory_sample", lambda: (81.0, 6.0))
        assert tp.run_night(PILOT, NOW, repo=repo, python=sys.executable, db_path=db) == 0
        n = night_row(db)
        record = tp.draw("pilot-x", COHORT, UNIVERSE, 5)
        assert (n["outcome"], n["exit_code"], n["seed"], n["universe_hash"], n["tickers"]) == (
            "ran",
            0,
            record["seed"],
            record["universe_hash"],
            5,
        )
        assert n["ended_at"] is not None
        samples = _query("SELECT available_pct, swap_used_mb FROM thesis_pilot_samples", (), db)
        assert samples and {(s["available_pct"], s["swap_used_mb"]) for s in samples} == {(81.0, 6.0)}

    def test_memory_is_sampled_repeatedly_while_the_batch_runs(self, world, monkeypatch):
        repo, db = world
        TestRunNight()._fake(monkeypatch)
        hashes = tf.current_hashes(lc.load_config(REPO / lc.CONFIG_PATH))
        monkeypatch.setattr(tp, "freeze_command", lambda python: [python, "-c", f"print({json.dumps(hashes)!r})"])
        monkeypatch.setattr(
            tp,
            "commands",
            lambda pilot, tickers, python, db_path=None: [[python, "-c", "import time; time.sleep(0.5)"]],
        )
        monkeypatch.setattr(tp, "SAMPLE_SECONDS", 0.05)
        monkeypatch.setattr(tp, "memory_sample", lambda: (1.0, 0.0))
        assert tp.run_night(PILOT, NOW, repo=repo, python=sys.executable, db_path=db) == 0
        assert len(_query("SELECT 1 FROM thesis_pilot_samples", (), db)) >= 3

    def test_a_refused_night_is_recorded_with_its_reason(self, world, monkeypatch):
        repo, db = world
        self._fake(monkeypatch)
        assert (
            tp.run_night(PILOT, datetime(2026, 11, 4, 6, 40, tzinfo=KST), repo=repo, python=sys.executable, db_path=db)
            == 5
        )
        assert (night_row(db)["outcome"], night_row(db)["exit_code"]) == ("refused:ollama_busy", 5)

    def test_a_night_without_a_session_leaves_no_record(self, world, monkeypatch):
        repo, db = world
        self._fake(monkeypatch)
        assert (
            tp.run_night(PILOT, datetime(2026, 11, 2, 10, 0, tzinfo=KST), repo=repo, python=sys.executable, db_path=db)
            == 0
        )
        assert night(db, "2026-11-02") is None

    def test_outside_production_nothing_is_written_or_run(self, world, monkeypatch):
        repo, db = world
        self._fake(monkeypatch)
        monkeypatch.delenv("NURI_ROLE")
        assert tp.run_night(PILOT, NOW, repo=repo, python=sys.executable, db_path=db) == 5
        assert night(db) is None and not (repo / "data" / "calls.jsonl").exists()

    def test_a_second_run_of_the_cohort_is_refused_by_the_record_even_without_the_lock(self, world, monkeypatch):
        """잠금이 풀린 뒤(첫 실행이 끝난 뒤)의 재실행 — 기본 키가 막고, 첫 기록을 덮어쓰지 않는다."""
        repo, db = world
        self._fake(monkeypatch)
        assert tp.run_night(PILOT, NOW, repo=repo, python=sys.executable, db_path=db) == 0
        first = night_row(db)
        assert tp.run_night(PILOT, NOW, repo=repo, python=sys.executable, db_path=db) == 5
        assert night(db) == first
        assert len((repo / "data" / "calls.jsonl").read_text().splitlines()) == 2

    def test_an_exception_is_recorded_and_raised(self, world, monkeypatch):
        repo, db = world
        self._fake(monkeypatch)
        monkeypatch.setattr(tp, "pinned_worktree", lambda repo, path: (_ for _ in ()).throw(OSError("disk full")))
        with pytest.raises(OSError):
            tp.run_night(PILOT, NOW, repo=repo, python=sys.executable, db_path=db)
        assert (night_row(db)["outcome"], night_row(db)["exit_code"]) == ("error:OSError", 1)


class TestMemorySample:
    def test_reads_the_available_level_and_swap_used(self, monkeypatch):
        outs = {
            "kern.memorystatus_level": "81\n",
            "vm.swapusage": "total = 2048.00M  used = 512.50M  free = 1535.50M  (encrypted)\n",
        }
        monkeypatch.setattr(tp, "_out", lambda argv: outs[argv[-1]])
        assert tp.memory_sample() == (81.0, 512.5)

    def test_it_never_runs_the_pressure_tool(self, monkeypatch):
        """`memory_pressure` 는 압박을 거는 도구다 — 읽기 전용 sysctl 만 부른다."""
        seen = []
        monkeypatch.setattr(tp, "_out", lambda argv: seen.append(argv) or "1")
        tp.memory_sample()
        assert [a[0] for a in seen] == ["sysctl", "sysctl"]

    def test_an_unreadable_host_gives_none_instead_of_failing(self, monkeypatch):
        def missing(argv):
            raise FileNotFoundError(argv[0])

        monkeypatch.setattr(tp, "_out", missing)
        assert tp.memory_sample() == (None, None)

    def test_unexpected_output_gives_none(self, monkeypatch):
        monkeypatch.setattr(tp, "_out", lambda argv: "nothing useful")
        assert tp.memory_sample() == (None, None)
