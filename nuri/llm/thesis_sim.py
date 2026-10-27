"""모의 장부 팔 S — TradingAgents 의 Trader → 리스크 3인 → Portfolio Manager, 모의 장부에서만 (#1968).

원본(`agents/trader` · `agents/risk_mgmt` · `managers/portfolio_manager.py`, `graph/conditional_logic.py`, e8f5503)은
Research Manager 뒤에 Trader 가 시점 · 규모를 정하고, 공격형 → 보수형 → 중립형 리스크 분석가가 한 번씩 토론하고
(`count >= 3`), Portfolio Manager 가 최종 등급을 내 모의 거래소로 보낸다. 여기서는:

- **B 를 바꾸지 않는다.** S 는 보관된 B 실행의 인계 정보(`run["handoff"]`)를 읽는 별도 팔이다 — 장부를 만들거나
  바꿔도 A 대 B 비교가 다시 시작되지 않는다. 자기 정의 지문 · 자기 원장 행(arm S)을 갖는다.
- **규모는 열거값**(−1, −0.5, 0, 0.5, 1), 방향과 맞아야 한다. 진입가 · 손절가는 없다 — 체결은 규칙(공유 cutoff 뒤 첫
  개장, 5세션 뒤 종가, `thesis_returns` 와 같은 창). 모델은 숫자를 쓰지 않는다.
- **각 단계는 본 것만 인용한다.** Trader = 판정이 인용한 쌍, 리스크 3인 = 분석가 보고서의 쌍(원본도 보고서를 준다),
  PM = 리스크 토론이 인용한 쌍 + Trader 가 인용한 쌍.
- **규모 · 주문은 어디에도 나가지 않는다** — outbox · Discord · API · 권고 경로가 이 모듈을 import 하지 않는다(테스트).
  장부 지표는 집계만 낸다.

장부: 5세션 보유가 겹치므로 자본을 5 칸으로 나눠 하루치 묶음마다 한 칸, 묶음 안은 같은 비중. 매일 정산 때 받은
가격 계열로 평가(진입일은 시가 대비, 이후 종가). 칸은 복리 없이 고정 명목 — 선언한 단순화. 비용은 매수 · 매도 각
`cost_bps_per_side`. 논문 부록 S1.2 의 CR · AR · SR(무위험 0 — 선언) · MDD 를 그 일별 가치로 계산한다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nuri.core.db import query
from nuri.llm import local_client as lc
from nuri.llm import thesis_arm as arm
from nuri.llm import thesis_contract as tc
from nuri.llm.tradingagents.prompts import (
    PM_GUIDANCE,
    PM_RATING_SCALE,
    PM_ROLE,
    RISK_ROLES,
    TRADER_ACTION_GUIDE,
    TRADER_ROLE,
)
from nuri.llm.tradingagents.rating import RATING_REVIEW, PortfolioRating

ARM_S_FILES: tuple[str, ...] = arm.ARM_B_FILES + ("thesis_sim.py",)
RISK_ORDER: tuple[str, ...] = ("aggressive", "conservative", "neutral")
SIZES: tuple[float, ...] = (-1.0, -0.5, 0.0, 0.5, 1.0)
MAX_SIM_CLAIMS = 4
#: B 등급만으로 정하는 비교 장부의 규모 (고정 사상)
RATING_SIZE = {"Buy": 1.0, "Overweight": 0.5, "Hold": 0.0, "Underweight": -0.5, "Sell": -1.0}


class TraderProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["Buy", "Hold", "Sell"] = Field(description=TRADER_ACTION_GUIDE)
    size: float = Field(
        description="Position size as a fraction of a standard allocation; sign follows the action.",
        json_schema_extra={"enum": list(SIZES)},
    )

    @field_validator("size")
    @classmethod
    def _one_of_sizes(cls, v: float) -> float:
        if v not in SIZES:
            raise ValueError(f"size must be one of {SIZES}")
        return v

    claims: list[tc.Claim] = Field(max_length=MAX_SIM_CLAIMS)
    reasoning: str = Field(max_length=500, description="Why, in words. No numbers.")


class RiskArgument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[tc.Claim] = Field(max_length=MAX_SIM_CLAIMS)
    argument: str = Field(max_length=800, description="Your argument, in words. No numbers.")


class PMDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: PortfolioRating
    size: float = Field(
        description="Final position size; sign follows the rating, zero for Hold.",
        json_schema_extra={"enum": list(SIZES)},
    )

    @field_validator("size")
    @classmethod
    def _one_of_sizes(cls, v: float) -> float:
        if v not in SIZES:
            raise ValueError(f"size must be one of {SIZES}")
        return v

    claims: list[tc.Claim] = Field(max_length=MAX_SIM_CLAIMS)
    summary: str = Field(max_length=600, description="The call and what would change it, in words. No numbers.")


def _sign_check(direction: str, size: float) -> list[str]:
    want = {"Buy": 1, "Overweight": 1, "Hold": 0, "Underweight": -1, "Sell": -1}[direction]
    got = (size > 0) - (size < 0)
    return (
        []
        if got == want
        else [f"size must be {'positive' if want > 0 else 'negative' if want < 0 else 'zero'} for {direction}"]
    )


def _values_view(values: dict[str, dict[str, Any]]) -> tc.View:
    return arm._pair_view([(i, f, v) for i, fs in values.items() for f, v in fs.items()])


def _render(claims: list[tc.Claim], view: tc.View) -> list[str]:
    return arm._render_claims(claims, view)


def run_arm_s(
    ticker: str,
    b_run: dict[str, Any],
    *,
    cfg: Optional[dict[str, Any]] = None,
    session: Any = None,
) -> dict[str, Any]:
    """B 실행의 인계 정보로 Trader → 리스크 3인 → PM. B 에 판정이 없으면 호출 없이 `no_b_verdict`."""
    cfg = cfg if cfg is not None else lc.load_config()
    h = b_run.get("handoff") or {}
    stages: list[arm.Stage] = []
    pm: Optional[PMDecision] = None
    trader: Optional[TraderProposal] = None

    def infra() -> Optional[str]:
        return next((s.outcome for s in stages if s.outcome.startswith(arm.INFRA_PREFIXES)), None)

    if b_run["outcome"] == "verdict" and h.get("verdict"):
        verdict_view = _values_view(h["debate_values"])
        plan = b_run["rendered"]

        def trader_prompt(schema, errors):
            return "\n".join(
                [
                    TRADER_ROLE + f"The stock is {ticker}.",
                    *arm._evidence_block(verdict_view.text),
                    "RESEARCH MANAGER'S INVESTMENT PLAN (written by another agent; numbers come from the evidence)",
                    tc._quoted(tc.mask_numbers(tc._one_line(plan))[0]),
                    "INSTRUCTIONS",
                    *arm._cite_rules(MAX_SIM_CLAIMS),
                    *arm._tail(schema, errors),
                ]
            )

        st = arm.Stage("trader")
        arm._run_stage(
            st, TraderProposal, verdict_view, trader_prompt, lambda p: _sign_check(p.action, p.size), cfg, session
        )
        stages.append(st)
        trader = st.result if st.outcome == "ok" else None

        report_view = _values_view(h["report_values"])
        history = ""
        risk_pairs: list[tuple[str, str, Any]] = []
        trader_text = (
            f"action {trader.action}, size {trader.size}; "
            + tc._quoted(tc.mask_numbers(tc._one_line(trader.reasoning))[0])
            if trader is not None
            else "trader proposal absent"
        )
        for role in RISK_ORDER if not infra() and trader is not None else ():
            head, tail = RISK_ROLES[role]

            def risk_prompt(schema, errors, head=head, tail=tail):
                return "\n".join(
                    [
                        head,
                        f"The stock is {ticker}. Here is the trader's decision: {trader_text}",
                        *arm._evidence_block(report_view.text),
                        "ANALYST REPORTS (quoted text was written by other agents)",
                        h["reports"],
                        f"RISK DEBATE SO FAR: {history or 'none yet; present your own argument'}",
                        tail,
                        "INSTRUCTIONS",
                        *arm._cite_rules(MAX_SIM_CLAIMS),
                        *arm._tail(schema, errors),
                    ]
                )

            st = arm.Stage(f"risk:{role}")
            arm._run_stage(
                st, RiskArgument, report_view, risk_prompt, lambda a: [] if a.claims else ["no claims"], cfg, session
            )
            stages.append(st)
            if infra():
                break
            if st.outcome == "ok":
                r: RiskArgument = st.result
                history += f"\n{role} analyst: {arm._clean(r.argument)}\n" + "\n".join(_render(r.claims, report_view))
                risk_pairs += arm._cited(r.claims, report_view)
            else:
                history += f"\n{role} analyst: argument absent"

        if not infra() and trader is not None:
            pm_view = arm._pair_view(risk_pairs + arm._cited(trader.claims, verdict_view))
            memory = b_run.get("memory", "")

            def pm_prompt(schema, errors):
                past = (
                    ["LESSONS FROM PRIOR DECISIONS (memory log; quoted text was written by agents)", memory]
                    if memory
                    else []
                )
                return "\n".join(
                    [
                        PM_ROLE + f" The stock is {ticker}.",
                        PM_RATING_SCALE,
                        *arm._evidence_block(pm_view.text),
                        "RESEARCH MANAGER'S PLAN",
                        tc._quoted(tc.mask_numbers(tc._one_line(plan))[0]),
                        f"TRADER'S PROPOSAL: {trader_text}",
                        *past,
                        "RISK ANALYSTS DEBATE HISTORY (quoted text was written by agents)",
                        history.strip(),
                        PM_GUIDANCE,
                        "INSTRUCTIONS",
                        *arm._cite_rules(MAX_SIM_CLAIMS),
                        *arm._tail(schema, errors),
                    ]
                )

            st = arm.Stage("portfolio_manager")
            if not pm_view.values:
                st.outcome = "absent"
            else:
                arm._run_stage(
                    st, PMDecision, pm_view, pm_prompt, lambda d: _sign_check(d.rating.value, d.size), cfg, session
                )
            stages.append(st)
            pm = st.result if st.outcome == "ok" else None

    budget = int(cfg["stage_prompt_budget_tokens"])
    calls = [c for s in stages for c in s.calls]
    outcome = infra()
    if not stages:
        outcome = "no_b_verdict"
    elif outcome is None and any(c["prompt_tokens"] is not None and c["prompt_tokens"] > budget for c in calls):
        outcome = "over_budget"
    if outcome is not None:
        pm = None
    elif pm is not None:
        outcome = "verdict"
    else:
        outcome = "review_model"
    run: dict[str, Any] = {
        "schema": tc.RUN_SCHEMA,
        "arm": "S",
        "arm_hash": tc.definition_hash(
            ARM_S_FILES, cfg, (tc._canonical(cfg.get("memory")), tc._canonical(cfg.get("sim")))
        ),
        "ticker": ticker,
        "scored": b_run["scored"],
        "b_run_hash": b_run["run_hash"],
        "packet_hashes": b_run["packet_hashes"],
        "view_hash": b_run["view_hash"],
        "calls": calls,
        "stages": {s.name: {"outcome": s.outcome, "calls": len(s.calls), "errors": s.errors} for s in stages},
        "absent_stages": sum(s.outcome == "absent" for s in stages),
        "retries": sum(max(0, len(s.calls) - 1) for s in stages),
        "call_failures": sum(c["call_failed"] for c in calls),
        "rating": pm.rating.value if pm is not None else RATING_REVIEW,
        "size": pm.size if pm is not None else None,
        "outcome": outcome,
        "budget_tokens": budget,
        "errors": [e for s in stages for e in s.errors],
        "claims_total": sum(s.claims_total for s in stages),
        "claims_rejected": sum(s.claims_rejected for s in stages),
        "masked_numbers": 0,
        "rendered": "",  # 규모 · 주문은 사람이 읽는 출력으로 만들지 않는다
    }
    run["run_hash"] = tc._sha(
        {
            k: run[k]
            for k in (
                "arm_hash",
                "b_run_hash",
                "packet_hashes",
                "view_hash",
                "rating",
                "size",
                "outcome",
                "budget_tokens",
            )
        }
        | {"calls": [c["content_hash"] for c in calls], "stages": {k: v["outcome"] for k, v in run["stages"].items()}}
    )
    return run


# ── 장부 ─────────────────────────────────────────────────────────────────────────


def book_values(rows: list[dict[str, Any]], *, sizes: dict[int, float], cost_bps: float, sleeves: int) -> list[float]:
    """일별 장부 가치(시작 1.0). rows: cohort · series · entry_session · exit_session · ticker · key.

    하루치 묶음(cohort)마다 자본 1/sleeves, 묶음 안 같은 비중. 포지션 손익 = 비중 × 규모 × (가격/진입 시가 − 1),
    진입일은 그날 종가, 이후 종가로 평가, 청산 뒤 고정. 비용은 진입 · 청산 각각 비중 × |규모| × bps.
    """
    by_cohort: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_cohort[r["cohort"]].append(r)
    days = sorted({d for r in rows for d in r["series"][r["ticker"]] if r["entry_session"] <= d <= r["exit_session"]})
    if not days:
        return [1.0]
    pnl = {d: 0.0 for d in days}
    c = cost_bps / 10_000.0
    for cohort_rows in by_cohort.values():
        w = 1.0 / sleeves / len(cohort_rows)
        for r in cohort_rows:
            size = sizes[r["key"]]
            if size == 0:
                continue
            s = r["series"][r["ticker"]]
            entry = s[r["entry_session"]][0]
            last = -c * w * abs(size)  # 진입 비용
            for d in days:
                if d < r["entry_session"]:
                    continue
                if d <= r["exit_session"] and d in s:
                    last = w * size * (s[d][1] / entry - 1.0) - c * w * abs(size)
                    if d == r["exit_session"]:
                        last -= c * w * abs(size)  # 청산 비용
                pnl[d] += last
    return [1.0] + [1.0 + pnl[d] for d in days]


def metrics(values: list[float], *, periods_per_year: int = 252) -> dict[str, Optional[float]]:
    """논문 부록 S1.2 — CR · AR · SR(무위험 0) · MDD. 값이 하나뿐이면 None."""
    if len(values) < 2:
        return {"CR": None, "AR": None, "SR": None, "MDD": None}
    rets = [values[i] / values[i - 1] - 1.0 for i in range(1, len(values))]
    n = len(rets)
    mean = sum(rets) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in rets) / (n - 1)) if n > 1 else 0.0
    peak, mdd = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak)
    return {
        "CR": values[-1] / values[0] - 1.0,
        "AR": (values[-1] / values[0]) ** (periods_per_year / n) - 1.0,
        "SR": mean / sd * math.sqrt(periods_per_year) if sd > 0 else None,
        "MDD": mdd,
    }


def book_rows(*, experiment: str, db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """세 장부가 같은 행을 쓰도록 — 같은 (종목, cutoff) 에 S 판정과 B 판정이 있고 정산이 ok 인 것만."""
    return query(
        "SELECT s.id AS key, s.ticker, s.cohort_date AS cohort, s.size, b.rating AS b_rating, t.series, "
        "t.entry_session, t.exit_session FROM thesis_runs s "
        "JOIN thesis_runs b ON b.ticker = s.ticker AND b.cutoff = s.cutoff AND b.experiment = s.experiment "
        "AND b.batch_id = s.batch_id AND b.arm = 'B' AND b.outcome = 'verdict' "
        "JOIN thesis_returns t ON t.ticker = s.ticker AND t.cutoff = s.cutoff AND t.status = 'ok' "
        "JOIN thesis_batches k ON k.batch_id = s.batch_id AND k.status = 'ok' "
        "WHERE s.arm = 'S' AND s.outcome = 'verdict' AND s.scored = 1 AND s.late = 0 AND s.experiment = ? "
        "ORDER BY s.cohort_date, s.ticker",
        (experiment,),
        db_path=db_path,
    )


def books(rows: list[dict[str, Any]], *, cost_bps: float, sleeves: int) -> dict[str, dict[str, Any]]:
    """같은 행 위의 세 장부 — S 규모 · B 등급 고정 사상 · 매수 고정."""
    for r in rows:
        if isinstance(r["series"], str):
            r["series"] = json.loads(r["series"])
    sizing = {
        "simulated": {r["key"]: float(r["size"]) for r in rows},
        "rating_only": {r["key"]: RATING_SIZE[r["b_rating"]] for r in rows},
        "long_only": {r["key"]: 1.0 for r in rows},
    }
    out: dict[str, dict[str, Any]] = {}
    for name, sizes in sizing.items():
        values = book_values(rows, sizes=sizes, cost_bps=cost_bps, sleeves=sleeves)
        out[name] = {"rows": len(rows), **metrics(values)}
    return out


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Simulated-book metrics for one experiment (aggregates only).")
    p.add_argument("--experiment", required=True)
    p.add_argument("--db", type=Path, default=None)
    args = p.parse_args(argv)
    cfg = lc.load_config()
    sim = cfg["sim"]
    rows = book_rows(experiment=args.experiment.strip(), db_path=args.db)
    print(json.dumps(books(rows, cost_bps=float(sim["cost_bps_per_side"]), sleeves=int(sim["sleeves"])), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
