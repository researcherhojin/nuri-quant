"""실험 창 동안 팔 정의 동결 (#1990)."""

from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from nuri.core.timezone import kst_now
from nuri.llm import local_client as lc
from nuri.llm import thesis_arm as arm
from nuri.llm import thesis_contract as tc
from nuri.llm import thesis_freeze as tf
from nuri.llm import thesis_sim as sim

REPO = Path(__file__).resolve().parents[2]
CFG = {"stage_prompt_budget_tokens": 1000, "memory": {"holding_sessions": 5}, "sim": {"sleeves": 5}}
START, END = date(2026, 11, 2), date(2026, 11, 20)
# 손으로 적지 않는다 — 팔에 파일이 더해지면 여기도 따라온다
FROZEN_FILES = sorted(set(tc.ARM_A_FILES) | set(arm.ARM_B_FILES) | set(sim.ARM_S_FILES))


def test_the_declared_windows_hold_today():
    """실제 가드 — 오늘(KST)이 선언된 창 안인데 팔 지문이 움직였으면 실패한다. 해제는 freeze 파일 편집으로."""
    assert tf.check(REPO / tf.FREEZE_PATH, REPO / lc.CONFIG_PATH) == []


def test_the_real_check_compares_against_today(tmp_path):
    """위 가드가 창이 선언된 날에도 돈다 — 빈 파일만으로는 날짜 비교 경로가 한 번도 실행되지 않는다."""
    cfg_path = REPO / lc.CONFIG_PATH
    hashes = tf.current_hashes(lc.load_config(cfg_path))
    today = kst_now().date()
    p = tmp_path / "f.yaml"
    for arms, expected in (({"A": hashes["A"]}, 0), ({"A": "0" * 64}, 1)):
        p.write_text(yaml.safe_dump({"freezes": [{"experiment": "x", "start": today, "end": today, "arms": arms}]}))
        assert len(tf.check(p, cfg_path)) == expected


@pytest.fixture
def llm_copy(tmp_path, monkeypatch):
    dst = tmp_path / "llm"
    for name in FROZEN_FILES:
        (dst / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(tc._LLM_DIR / name, dst / name)
    monkeypatch.setattr(tc, "_LLM_DIR", dst)
    return dst


def frozen(cfg=CFG):
    return [tf.Freeze("pilot", START, END, tf.current_hashes(cfg))]


class TestDoneWhen:
    @pytest.mark.parametrize("name", FROZEN_FILES)
    def test_editing_a_frozen_file_fails_only_inside_the_window(self, llm_copy, name):
        freezes = frozen()
        (llm_copy / name).write_bytes((llm_copy / name).read_bytes() + b"\n# edit\n")
        now = tf.current_hashes(CFG)
        for day in (START, START + timedelta(days=5), END):  # 양 끝 포함
            assert tf.violations(freezes, day, now), (name, day)
        for day in (START - timedelta(days=1), END + timedelta(days=1)):
            assert tf.violations(freezes, day, now) == [], (name, day)

    def test_an_untouched_definition_passes_inside_the_window(self):
        assert tf.violations(frozen(), START, tf.current_hashes(CFG)) == []

    @pytest.mark.parametrize(
        ("change", "moved"),
        [
            ({"stage_prompt_budget_tokens": 999}, ["A", "B", "S"]),
            ({"memory": {"holding_sessions": 10}}, ["B", "S"]),
            ({"sim": {"sleeves": 4}}, ["S"]),
        ],
    )
    def test_config_edits_move_the_arms_that_read_them(self, change, moved):
        out = tf.violations(frozen(), START, tf.current_hashes({**CFG, **change}))
        assert [v.split(" arm ")[1][0] for v in out] == moved

    def test_only_the_declared_arms_are_frozen(self):
        only_a = [tf.Freeze("pilot", START, END, {"A": tf.current_hashes(CFG)["A"]})]
        assert tf.violations(only_a, START, tf.current_hashes({**CFG, "sim": {"sleeves": 4}})) == []


def entry(**over):
    e = {"experiment": "pilot", "start": START, "end": END, "arms": {"A": "a" * 64}}
    return {k: v for k, v in {**e, **over}.items() if v is not ...}


class TestFreezeFile:
    def test_the_tracked_file_parses(self):
        tf.load(REPO / tf.FREEZE_PATH)

    def test_a_valid_window_round_trips_through_yaml(self, tmp_path):
        p = tmp_path / "f.yaml"
        p.write_text(
            "freezes:\n  - experiment: pilot\n    start: 2026-11-02\n    end: 2026-11-20\n"
            f"    arms: {{B: {'b' * 64}}}\n"
        )
        assert tf.load(p) == [tf.Freeze("pilot", START, END, {"B": "b" * 64})]

    @pytest.mark.parametrize(
        "text",
        [
            # 끝에 붙은 빈 목록이 앞의 창을 덮어쓰면 가드가 꺼진다 (Codex 리뷰)
            f"freezes:\n  - {{experiment: x, start: 2026-11-02, end: 2026-11-20, arms: {{A: {'a' * 64}}}}}\nfreezes: []\n",
            f"freezes:\n  - {{experiment: x, start: 2026-11-02, end: 2026-11-20, arms: {{A: {'a' * 64}, A: {'b' * 64}}}}}\n",
        ],
    )
    def test_duplicate_keys_are_refused(self, tmp_path, text):
        p = tmp_path / "f.yaml"
        p.write_text(text)
        with pytest.raises(ValueError, match="duplicate keys"):
            tf.load(p)

    @pytest.mark.parametrize(
        "doc",
        [
            None,
            {"freezes": None},
            {"freezes": [], "extra": 1},
            {"freezes": ["pilot"]},
            {"freezes": [entry(arms=...)]},
            {"freezes": [entry(note="x")]},
            {"freezes": [entry(experiment="")]},
            {"freezes": [entry(start="2026-11-02")]},  # 따옴표 날짜
            {"freezes": [entry(end=yaml.safe_load("2026-11-20 10:00:00"))]},  # 시각
            {"freezes": [entry(start=END, end=START)]},
            {"freezes": [entry(arms={})]},
            {"freezes": [entry(arms={"C": "a" * 64})]},
            {"freezes": [entry(arms={"A": "A" * 64})]},
            {"freezes": [entry(arms={"A": "a" * 63})]},
            {"freezes": [entry(arms={"A": None})]},
        ],
    )
    def test_a_malformed_declaration_fails_instead_of_switching_the_guard_off(self, doc):
        with pytest.raises(ValueError):
            tf.parse(doc)


def test_the_cli_prints_the_current_hashes(monkeypatch, capsys):
    monkeypatch.setattr(lc, "load_config", lambda: CFG)
    assert tf.main() == 0
    assert json.loads(capsys.readouterr().out) == tf.current_hashes(CFG)
