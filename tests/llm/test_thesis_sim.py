"""모의 장부 팔 S (#1968) — 단계 · 인용 범위 · 규모 검증 · 장부 계산 · 경계. 모델 · 가격은 가짜다."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest
import requests

from nuri.core.db import get_db, init_db
from nuri.llm import local_client as lc
from nuri.llm import thesis_arm as arm
from nuri.llm import thesis_sim as sim
from nuri.llm.tradingagents.prompts import PM_ROLE, RISK_ROLES, TRADER_ROLE

CFG = {"stage_prompt_budget_tokens": 1000}


def claim(side, eid, f, point="p"):
    return {"side": side, "evidence_id": eid, "field": f, "point": point}


def b_run(outcome="verdict", memory=""):
    return {
        "outcome": outcome,
        "ticker": "T0",
        "scored": True,
        "run_hash": "bh",
        "packet_hashes": ["tp", "mp"],
        "view_hash": "vh",
        "rendered": "**Rating**: Overweight\n- [bull] up 12% — `prices:1` last_close = 101.5",
        "memory": memory,
        "handoff": {
            "reports": 'market analyst report: summary "up"',
            "report_values": {
                "prices:1": {"last_close": 101.5},
                "macro:3": {"latest": 18.2},
                "fundamentals:2": {"pe_ratio": 30.1},
            },
            "debate": 'bull analyst: "trend"',
            "debate_values": {"prices:1": {"last_close": 101.5}, "fundamentals:2": {"pe_ratio": 30.1}},
            "verdict": {"rating": "Overweight"},
        },
    }


TRADER_OK = {"action": "Buy", "size": 0.5, "claims": [claim("bull", "prices:1", "last_close")], "reasoning": "trend"}
RISK_OK = {
    "aggressive": {"claims": [claim("bull", "prices:1", "last_close")], "argument": "go"},
    "conservative": {"claims": [claim("bear", "macro:3", "latest")], "argument": "careful"},
    "neutral": {"claims": [claim("bear", "fundamentals:2", "pe_ratio")], "argument": "balance"},
}
PM_OK = {"rating": "Overweight", "size": 0.5, "claims": [claim("bull", "prices:1", "last_close")], "summary": "go"}


def stage_of(prompt):
    if prompt.startswith(TRADER_ROLE):
        return "trader"
    for role, (head, _) in RISK_ROLES.items():
        if prompt.startswith(head):
            return f"risk:{role}"
    if prompt.startswith(PM_ROLE):
        return "pm"
    raise AssertionError(prompt[:60])


class Fake:
    def __init__(self, answers=None, tokens=100):
        self.answers = {k: list(v) for k, v in (answers or {}).items()}
        self.prompts: list[tuple[str, str]] = []
        self.schemas: dict[str, dict] = {}
        self.tokens = tokens

    def default(self, stage):
        if stage.startswith("risk:"):
            return RISK_OK[stage.split(":")[1]]
        return {"trader": TRADER_OK, "pm": PM_OK}[stage]

    def __call__(self, prompt, *, cfg, schema, session):
        stage = stage_of(prompt)
        self.prompts.append((stage, prompt))
        self.schemas[stage] = schema
        q = self.answers.get(stage)
        a = q.pop(0) if q else self.default(stage)
        if isinstance(a, Exception):
            raise a
        text = a if isinstance(a, str) else json.dumps(a)
        return {
            "content_hash": hashlib.sha256((prompt + text).encode()).hexdigest(),
            "archive_path": None,
            "response": {"response": text, "prompt_eval_count": self.tokens},
        }

    def stages(self):
        return [s for s, _ in self.prompts]


def run_s(monkeypatch, answers=None, b=None, **kw):
    fake = Fake(answers, **kw)
    monkeypatch.setattr(lc, "generate", fake)
    return sim.run_arm_s("T0", b or b_run(), cfg=dict(CFG)), fake


class TestStages:
    def test_upstream_order_and_a_sized_verdict(self, monkeypatch):
        run, fake = run_s(monkeypatch)
        assert fake.stages() == ["trader", "risk:aggressive", "risk:conservative", "risk:neutral", "pm"]
        assert run["outcome"] == "verdict" and (run["rating"], run["size"]) == ("Overweight", 0.5)
        assert run["arm"] == "S" and run["b_run_hash"] == "bh" and run["rendered"] == ""

    def test_each_stage_cites_only_what_it_saw(self, monkeypatch):
        _, fake = run_s(monkeypatch)

        def ids(stage):
            return set(fake.schemas[stage]["$defs"]["Claim"]["properties"]["evidence_id"]["enum"])

        assert ids("trader") == {"prices:1", "fundamentals:2"}  # 판정이 인용한 쌍
        assert ids("risk:aggressive") == {"prices:1", "macro:3", "fundamentals:2"}  # 분석가 보고서의 쌍
        assert ids("pm") == {"prices:1", "macro:3", "fundamentals:2"}  # 리스크 토론 + Trader 가 인용한 쌍

    def test_the_risk_debate_runs_in_order_and_each_sees_the_previous(self, monkeypatch):
        _, fake = run_s(monkeypatch)
        p = dict(fake.prompts)
        assert "none yet; present your own argument" in p["risk:aggressive"]
        assert "aggressive analyst:" in p["risk:conservative"]
        assert "conservative analyst:" in p["risk:neutral"] and "aggressive analyst:" in p["risk:neutral"]

    def test_the_pm_gets_memory_and_the_upstream_scale(self, monkeypatch):
        from nuri.llm.tradingagents.prompts import PM_GUIDANCE, PM_RATING_SCALE

        _, fake = run_s(monkeypatch, b=b_run(memory="LESSON BLOCK"))
        pm = dict(fake.prompts)["pm"]
        assert "LESSON BLOCK" in pm and PM_RATING_SCALE in pm and PM_GUIDANCE in pm

    def test_numbers_in_upstream_text_reaching_s_are_masked(self, monkeypatch):
        _, fake = run_s(monkeypatch)
        assert "12%" not in dict(fake.prompts)["trader"] and "up #%" in dict(fake.prompts)["trader"]


class TestSizesAndSigns:
    @pytest.mark.parametrize(
        ("over", "error"),
        [
            ({"size": 0.3}, "schema"),
            ({"action": "Buy", "size": -0.5}, "size must be positive for Buy"),
            ({"action": "Hold", "size": 0.5}, "size must be zero for Hold"),
            ({"action": "Sell", "size": 0.0}, "size must be negative for Sell"),
        ],
    )
    def test_a_trader_size_must_be_listed_and_match_the_action(self, monkeypatch, over, error):
        bad = TRADER_OK | over
        run, fake = run_s(monkeypatch, {"trader": [bad, bad]})
        assert run["outcome"] == "review_model" and fake.stages() == ["trader", "trader"]
        assert any(error in e for e in run["stages"]["trader"]["errors"])

    @pytest.mark.parametrize(("size", "error"), [(0.5, "size must be negative for Underweight"), (0.3, "schema")])
    def test_a_pm_size_must_match_the_rating(self, monkeypatch, size, error):
        bad = PM_OK | {"rating": "Underweight", "size": size}
        run, _ = run_s(monkeypatch, {"pm": [bad, bad]})
        assert run["outcome"] == "review_model" and run["size"] is None
        assert any(error in e for e in run["stages"]["portfolio_manager"]["errors"])

    def test_the_schema_lists_the_allowed_sizes(self):
        assert sim.TraderProposal.model_json_schema()["properties"]["size"]["enum"] == list(sim.SIZES)


class TestOutcomes:
    def test_no_b_verdict_means_no_calls(self, monkeypatch):
        run, fake = run_s(monkeypatch, b=b_run(outcome="review_model"))
        assert run["outcome"] == "no_b_verdict" and fake.prompts == [] and run["rating"] == sim.RATING_REVIEW

    def test_an_absent_trader_stops_before_the_risk_debate(self, monkeypatch):
        run, fake = run_s(monkeypatch, {"trader": ["x", "x"]})
        assert fake.stages() == ["trader", "trader"] and run["outcome"] == "review_model"

    def test_an_absent_risk_analyst_is_recorded_and_the_pm_still_runs(self, monkeypatch):
        run, fake = run_s(monkeypatch, {"risk:conservative": ["x", "x"]})
        assert run["stages"]["risk:conservative"]["outcome"] == "absent" and run["outcome"] == "verdict"
        assert "conservative analyst: argument absent" in dict(fake.prompts)["pm"]

    def test_a_risk_analyst_must_cite(self, monkeypatch):
        empty = {"claims": [], "argument": "x"}
        run, _ = run_s(monkeypatch, {"risk:aggressive": [empty, empty]})
        assert run["stages"]["risk:aggressive"]["errors"] == ["no claims"]

    def test_an_infrastructure_failure_voids_the_run(self, monkeypatch):
        run, fake = run_s(monkeypatch, {"risk:aggressive": [requests.Timeout("x")]})
        assert run["outcome"] == "transport:Timeout" and "pm" not in fake.stages() and run["size"] is None

    def test_over_budget(self, monkeypatch):
        run, _ = run_s(monkeypatch, tokens=1001)
        assert run["outcome"] == "over_budget" and run["size"] is None

    def test_a_pm_with_nothing_cited_is_absent(self, monkeypatch):
        b = b_run()
        b["handoff"]["report_values"] = {}
        run, fake = run_s(monkeypatch, {}, b=b)
        trader_only = TRADER_OK | {"claims": []}
        run, fake = run_s(monkeypatch, {"trader": [trader_only]}, b=b)
        assert run["stages"]["portfolio_manager"]["outcome"] == "absent" and "pm" not in fake.stages()


class TestPairing:
    def test_s_runs_after_b_on_the_same_pair(self, monkeypatch):
        calls = []
        monkeypatch.setattr(arm, "run_arm_b", lambda t, p, memory="", **kw: calls.append("B") or b_run())
        monkeypatch.setattr(
            sim, "run_arm_s", lambda t, b, cfg=None, session=None: calls.append(("S", b["run_hash"])) or {"arm": "S"}
        )
        out = arm.run_pair("T0", {}, ("B", "S"), cfg=dict(CFG))
        assert calls == ["B", ("S", "bh")] and [r.get("arm") for r in out] == [None, "S"]

    def test_s_without_b_is_refused(self):
        with pytest.raises(ValueError, match="consumes arm B"):
            arm.run_pair("T0", {}, ("A", "S"), cfg=dict(CFG))


# ── 장부 ──

D = ["2026-10-23", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29"]


def row(key, cohort, ticker, opens_closes, entry=D[0], exit_=D[-1]):
    return {
        "key": key,
        "cohort": cohort,
        "ticker": ticker,
        "series": {ticker: opens_closes},
        "entry_session": entry,
        "exit_session": exit_,
    }


class TestBook:
    def test_values_match_a_hand_computation(self):
        """한 묶음 · 두 종목 · 2칸. 비중 = 1/2/2 = 0.25. A +1 · B −0.5, 비용 10bp/쪽."""
        a = {D[0]: [100.0, 102.0], D[1]: [102.0, 104.0]}
        b = {D[0]: [50.0, 49.0], D[1]: [49.0, 48.0]}
        rows = [row(1, "c1", "A", a, exit_=D[1]), row(2, "c1", "B", b, exit_=D[1])]
        v = sim.book_values(rows, sizes={1: 1.0, 2: -0.5}, cost_bps=10, sleeves=2)
        w, c = 0.25, 0.001
        day0 = w * 1.0 * (102 / 100 - 1) - c * w * 1.0 + w * -0.5 * (49 / 50 - 1) - c * w * 0.5
        day1 = (w * 1.0 * (104 / 100 - 1) - 2 * c * w * 1.0) + (w * -0.5 * (48 / 50 - 1) - 2 * c * w * 0.5)
        assert v == pytest.approx([1.0, 1.0 + day0, 1.0 + day1])

    def test_a_closed_position_stays_fixed_and_a_later_cohort_adds(self):
        a = {D[0]: [100.0, 110.0], D[1]: [110.0, 120.0]}
        b = {D[1]: [10.0, 11.0], D[2]: [11.0, 12.0]}
        rows = [row(1, "c1", "A", a, exit_=D[0]), row(2, "c2", "B", b, entry=D[1], exit_=D[2])]
        v = sim.book_values(rows, sizes={1: 1.0, 2: 1.0}, cost_bps=0, sleeves=1)
        assert v == pytest.approx([1.0, 1.10, 1.10 + 0.10, 1.10 + 0.20])

    def test_zero_size_and_no_days(self):
        a = {D[0]: [100.0, 110.0]}
        assert sim.book_values([row(1, "c1", "A", a, exit_=D[0])], sizes={1: 0.0}, cost_bps=10, sleeves=1) == [1.0, 1.0]
        assert sim.book_values([], sizes={}, cost_bps=10, sleeves=1) == [1.0]

    def test_metrics_match_the_paper_formulas(self):
        values = [1.0, 1.1, 0.99, 1.2]
        m = sim.metrics(values, periods_per_year=252)
        rets = [0.1, 0.99 / 1.1 - 1, 1.2 / 0.99 - 1]
        mean = sum(rets) / 3
        sd = (sum((r - mean) ** 2 for r in rets) / 2) ** 0.5
        assert m["CR"] == pytest.approx(0.2)
        assert m["AR"] == pytest.approx(1.2 ** (252 / 3) - 1)
        assert m["SR"] == pytest.approx(mean / sd * 252**0.5)
        assert m["MDD"] == pytest.approx((1.1 - 0.99) / 1.1)
        assert sim.metrics([1.0]) == {"CR": None, "AR": None, "SR": None, "MDD": None}
        assert sim.metrics([1.0, 1.0, 1.0])["SR"] is None

    def test_three_books_on_identical_rows(self):
        a = {d: [100.0, 101.0 if d != D[-1] else 110.0] for d in D}
        rows = [row(1, "c1", "A", a) | {"size": -0.5, "b_rating": "Overweight"}]
        out = sim.books(rows, cost_bps=0, sleeves=1)
        assert out["simulated"]["CR"] == pytest.approx(-0.05) and out["rating_only"]["CR"] == pytest.approx(0.05)
        assert out["long_only"]["CR"] == pytest.approx(0.10) and {v["rows"] for v in out.values()} == {1}


class TestBookRows:
    @pytest.fixture
    def db(self, tmp_path, monkeypatch):
        p = tmp_path / "s.db"
        init_db(p)
        return p

    def _seed(self, db, *, s_late=0, batch_status="ok", ret_status="ok", experiment="exp"):
        with get_db(db) as conn:
            conn.execute("INSERT INTO thesis_batches VALUES ('bk', 'exp', 's', 'c', 'e', 'c', ?)", (batch_status,))
            for arm_, rating, size, late in (("B", "Overweight", None, 0), ("S", "Buy", 1.0, s_late)):
                conn.execute(
                    "INSERT INTO thesis_runs (experiment, batch_id, cohort_date, arm, arm_hash, ticker, cutoff, late, "
                    "scored, run_hash, packet_hashes, view_hash, prompt_hashes, call_hashes, runtime, budget_tokens, "
                    "rating, size, outcome) VALUES (?, 'bk', '2026-10-23', ?, 'h', 'T0', 'C', ?, 1, ?, '[]', 'v', "
                    "'[]', '[]', '{}', 14000, ?, ?, 'verdict')",
                    (experiment, arm_, late, arm_, rating, size),
                )
            conn.execute(
                "INSERT INTO thesis_returns VALUES ('T0', 'C', ?, ?, ?, 'x', 0.1, 'SPY', 0.0, 0.1, ?, 'f')",
                (ret_status, D[0], D[-1], json.dumps({"T0": {d: [1.0, 1.0 if d != D[-1] else 1.1] for d in D}})),
            )

    def test_a_clean_pair_is_selected(self, db):
        self._seed(db)
        rows = sim.book_rows(experiment="exp", db_path=db)
        assert [(r["ticker"], r["size"], r["b_rating"]) for r in rows] == [("T0", 1.0, "Overweight")]

    @pytest.mark.parametrize(
        "over", [{"s_late": 1}, {"batch_status": "canary_changed"}, {"ret_status": "missing"}, {"experiment": "other"}]
    )
    def test_late_unverified_unsettled_or_other_experiment_rows_are_left_out(self, db, over):
        self._seed(db, **over)
        assert sim.book_rows(experiment="exp", db_path=db) == []

    def test_cli_prints_aggregates_only(self, db, monkeypatch, capsys):
        self._seed(db)
        monkeypatch.setattr(lc, "load_config", lambda: {"sim": {"cost_bps_per_side": 0, "sleeves": 1}})
        assert sim.main(["--experiment", "exp", "--db", str(db)]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["long_only"]["CR"] == pytest.approx(0.1) and "T0" not in json.dumps(out)


def test_no_user_facing_path_imports_the_simulated_book():
    """규모 · 주문은 outbox · Discord · API · 권고로 나가지 않는다 — 그 경로들이 이 모듈을 import 하지 않는다."""
    root = Path(__file__).resolve().parents[2] / "nuri"
    offenders = []
    for sub in ("agents", "api", "alerts", "trading"):
        for f in (root / sub).rglob("*.py"):
            tree = ast.parse(f.read_text())
            for n in ast.walk(tree):
                names = (
                    [n.module or ""]
                    if isinstance(n, ast.ImportFrom)
                    else [a.name for a in n.names]
                    if isinstance(n, ast.Import)
                    else []
                )
                if isinstance(n, ast.ImportFrom) and n.module == "nuri.llm":
                    names += [f"nuri.llm.{a.name}" for a in n.names]
                if any(m.startswith("nuri.llm.thesis_sim") for m in names):
                    offenders.append(str(f.relative_to(root)))
    assert offenders == []


class TestReplayAndCalendar:
    def test_s_archive_replays_only_s_with_the_original_b(self, monkeypatch, tmp_path):
        cfg = dict(CFG, archive_dir=str(tmp_path))
        fake = Fake()
        monkeypatch.setattr(lc, "generate", fake)
        original_b = b_run(memory="ARCHIVED LESSON")
        run = sim.run_arm_s("T0", original_b, cfg=cfg)
        path = arm.tc.archive(run, {}, cfg)
        monkeypatch.setattr(lc, "load_config", lambda: cfg)
        monkeypatch.setattr(arm, "run_arm_b", lambda *a, **kw: pytest.fail("reran B"))
        monkeypatch.setattr(arm.thesis_memory, "past_context", lambda *a, **kw: pytest.fail("read memory"))
        fake.prompts.clear()
        assert arm.main(["--replay", str(path)]) == 0
        assert fake.stages() == ["trader", "risk:aggressive", "risk:conservative", "risk:neutral", "pm"]
        replayed = json.loads(path.read_text())["run"]
        assert replayed["run_hash"] == run["run_hash"]
        assert replayed["b_run"] == original_b
        assert "ARCHIVED LESSON" in dict(fake.prompts)["pm"]

    def test_missing_sessions_are_rejected(self):
        sparse = {D[0]: [100.0, 100.0], D[-1]: [100.0, 104.0]}
        with pytest.raises(ValueError, match="missing.*2026-10-26"):
            sim.book_values([row(1, "c1", "T0", sparse)], sizes={1: 1.0}, cost_bps=0, sleeves=1)

    def test_idle_sessions_count_in_the_metric_period(self):
        rows = [
            row(1, "c1", "T0", {D[0]: [100.0, 101.0]}, exit_=D[0]),
            row(2, "c2", "T1", {D[-1]: [100.0, 101.0]}, entry=D[-1]),
        ]
        values = sim.book_values(rows, sizes={1: 1.0, 2: 1.0}, cost_bps=0, sleeves=1)
        assert values == pytest.approx([1.0, 1.01, 1.01, 1.01, 1.01, 1.02])

    @pytest.mark.parametrize("change", ["missing", "hash", "ticker"])
    def test_s_replay_refuses_missing_or_mismatched_b(self, monkeypatch, tmp_path, capsys, change):
        cfg = dict(CFG, archive_dir=str(tmp_path))
        monkeypatch.setattr(lc, "generate", Fake())
        run = sim.run_arm_s("T0", b_run(), cfg=cfg)
        if change == "missing":
            run.pop("b_run", None)
        elif change == "hash":
            run["b_run"]["run_hash"] = "different"
        else:
            run["b_run"]["ticker"] = "OTHER"
        path = arm.tc.archive(run, {}, cfg)
        monkeypatch.setattr(lc, "load_config", lambda: cfg)
        monkeypatch.setattr(lc, "generate", lambda *a, **kw: pytest.fail("called the model"))
        assert arm.main(["--replay", str(path)]) == 2
        assert "no matching archived B input" in capsys.readouterr().err

    @pytest.mark.parametrize("price", [float("nan"), float("inf"), 0.0, -1.0])
    def test_invalid_daily_prices_are_rejected(self, price):
        series = {d: [100.0, price if d == D[1] else 104.0] for d in D}
        with pytest.raises(ValueError, match="invalid prices"):
            sim.book_values([row(1, "c1", "T0", series)], sizes={1: 1.0}, cost_bps=0, sleeves=1)

    def test_market_holidays_do_not_need_prices(self):
        series = {"2026-11-25": [100.0, 101.0], "2026-11-27": [101.0, 102.0]}
        r = row(1, "c1", "T0", series, entry="2026-11-25", exit_="2026-11-27")
        assert sim.book_values([r], sizes={1: 1.0}, cost_bps=0, sleeves=1) == pytest.approx([1.0, 1.01, 1.02])

    def test_fills_use_entry_open_and_never_a_later_open(self):
        series = {d: [999.0, 110.0] for d in D}
        series[D[0]] = [100.0, 110.0]
        series["2026-10-30"] = [1.0, 5000.0]  # 보유 창 밖 가격은 집계하지 않는다
        values = sim.book_values([row(1, "c1", "T0", series)], sizes={1: 1.0}, cost_bps=0, sleeves=1)
        assert values == pytest.approx([1.0] + [1.1] * len(D))
