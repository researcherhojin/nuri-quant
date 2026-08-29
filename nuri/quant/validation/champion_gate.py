"""Champion-challenger 승격 게이트 (#1307) — 캠페인 간 순차 통제.

`variant_walkforward` 의 gate 는 **한 캠페인 안**의 FWER(Bonferroni + frozen holdout)만
통제한다. 탐색은 순차·적응적이다 — 제안→기각→변형 재제안이 캠페인을 거듭하면 정적
alpha 는 시간축 p-hacking 이 된다 (Codex challenge P1). 이 모듈이 그 축을 통제한다:

- **Attempt ledger**: 기각 포함 모든 시도를 `challenger_attempts` 에 기록 (#1305 바인딩).
- **Alpha-spending (반감)**: 캠페인 j 의 배정 = `alpha_total / 2^j` — 무한 반복해도 합이
  예산을 넘지 않는다. 캠페인 안에서는 다시 검정 변형 수로 Bonferroni 분할.
- **Holdout retirement**: 같은 holdout 세대를 `holdout_max_uses` 캠페인까지만 열람.
  소진 후 verdict 는 `holdout_retired` — 새 `holdout_version` 사전등록 PR 전까지
  승격 제안 불가 (재사용된 봉인 구간은 더 이상 봉인이 아니다).

**기계는 기각만 자동이다.** `promotion_candidate` 는 제안 — 승격은 항상 사람의
STRATEGY PR (§2.6 운용 원칙 5). evidence_axis='research' (walk-forward) 전용 —
§3.11 라이브 결정원장 판정('live')과 한 verdict 안에서 섞지 않는다.

동일-조건 비교는 구조가 보장한다: champion(baseline)과 challenger 는 같은
`run_variant_search` 캠페인의 동일 패널·동일 warmup·동일 code_rev 산출이고, 그
바인딩이 attempt 행에 남는다. 캠페인 **간** 메트릭을 합치는 소비자는 반드시
`evidence_binding.require_measurable` 을 거칠 것 (#1305 mixed-sample 규칙).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from nuri.core.db import log_challenger_attempt, query

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "walkforward.yaml"

#: v1 은 variant family 만 배선 — exit_walkforward 는 결과 형태가 달라 별도 어댑터 필요.
FAMILY_VARIANT = "variant"


def _load_gate_config(path: Optional[Path] = None) -> dict:
    """config/walkforward.yaml `champion_gate:` 로드 (pre-registered — 변경은 STRATEGY PR)."""
    with open(path or _CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    gate = cfg.get("champion_gate")
    if not gate:
        raise ValueError("config/walkforward.yaml 에 champion_gate 섹션이 없다 (#1307 사전등록)")
    return gate


def campaign_alpha(alpha_total: float, campaign_seq: int) -> float:
    """캠페인 j 배정 alpha = alpha_total / 2^j — 반감 스펜딩.

    sum_{j>=1} alpha_total/2^j = alpha_total 이라 캠페인을 무한 반복해도 family 의
    평생 오류 예산을 넘지 않는다. 첫 캠페인부터 정적 alpha 의 절반 — 순차 탐색의
    입장료다.
    """
    if campaign_seq < 1:
        raise ValueError(f"campaign_seq must be >= 1, got {campaign_seq}")
    return alpha_total / (2.0**campaign_seq)


def next_campaign_seq(family: str, db_path: Optional[Path] = None) -> int:
    """다음 캠페인 번호 = 원장 최대 + 1 (기각 이력이 사라지면 spending 이 무너진다)."""
    rows = query(
        "SELECT MAX(campaign_seq) AS m FROM challenger_attempts WHERE family = ?",
        (family,),
        db_path=db_path,
    )
    return int(rows[0]["m"] or 0) + 1


def holdout_uses(family: str, holdout_id: str, db_path: Optional[Path] = None) -> int:
    """해당 holdout 세대를 실제로 열람(소비)한 캠페인 수."""
    rows = query(
        """SELECT COUNT(DISTINCT campaign_seq) AS n FROM challenger_attempts
           WHERE family = ? AND holdout_id = ? AND holdout_consumed = 1""",
        (family, holdout_id),
        db_path=db_path,
    )
    return int(rows[0]["n"])


def adjudicate(
    run_result: dict[str, Any],
    *,
    family: str = FAMILY_VARIANT,
    gate_config: Optional[dict] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """`run_variant_search` 결과 1건(=캠페인 1회)을 판정하고 원장에 기록.

    challenger 별 verdict:
    - `holdout_retired` — 이 캠페인 이전에 holdout 사용 횟수가 이미 소진. 승격 제안 불가.
      (runner 가 이미 열람한 것은 되돌릴 수 없으므로 소비로는 계속 센다.)
    - `promotion_candidate` — runner 의 discovery+holdout 통과 AND 순차 임계
      (campaign_alpha / n_test) 로 재검. **제안일 뿐** — 승격은 STRATEGY PR.
    - `rejected` — 그 외 전부.

    baseline(champion)은 대조군이라 행을 만들지 않는다 — champion 컬럼에 이름만 남는다.
    """
    gate = gate_config or _load_gate_config()
    alpha_total = float(gate["alpha_total"])
    max_uses = int(gate["holdout_max_uses"])
    holdout_id = f"{gate['holdout_version']}:{family}"

    seq = next_campaign_seq(family, db_path=db_path)
    alpha_c = campaign_alpha(alpha_total, seq)
    n_test = max(int(run_result["n_test_variants"]), 1)
    alpha_eff_seq = alpha_c / n_test

    prior_uses = holdout_uses(family, holdout_id, db_path=db_path)
    retired = prior_uses >= max_uses

    variants = run_result["variants"]
    champion = next((v["name"] for v in variants if v.get("baseline")), None)
    # 캠페인 단위 holdout 소비: 어느 한 변형이라도 봉인을 열었으면 1회 소비
    consumed = any(v.get("holdout_sharpe") is not None for v in variants)

    verdicts = []
    for v in variants:
        if v.get("baseline"):
            continue
        p = v.get("p_value")
        sequential_pass = p is not None and p < alpha_eff_seq
        if retired:
            verdict = "holdout_retired"
        elif v.get("promotion_eligible") and sequential_pass:
            verdict = "promotion_candidate"
        else:
            verdict = "rejected"
        log_challenger_attempt(
            family=family,
            campaign_seq=seq,
            challenger=v["name"],
            champion=champion,
            verdict=verdict,
            alpha_spent=alpha_eff_seq,
            p_value=p,
            oos_sharpe=v.get("oos_sharpe_pooled"),
            holdout_sharpe=v.get("holdout_sharpe"),
            holdout_id=holdout_id,
            holdout_consumed=consumed,
            walkforward_run_id=v.get("walkforward_run_id"),
            metrics={
                "discovery_passed": v.get("discovery_passed"),
                "holdout_passed": v.get("holdout_passed"),
                "runner_alpha_effective": v.get("alpha_effective"),
                "sequential_alpha_effective": alpha_eff_seq,
                "campaign_alpha": alpha_c,
                "prior_holdout_uses": prior_uses,
            },
            db_path=db_path,
        )
        verdicts.append({"challenger": v["name"], "verdict": verdict, "p_value": p})

    candidates = [x["challenger"] for x in verdicts if x["verdict"] == "promotion_candidate"]
    if candidates:
        logger.info("promotion_candidate (제안 — 승격은 STRATEGY PR): %s", candidates)
    return {
        "family": family,
        "campaign_seq": seq,
        "campaign_alpha": alpha_c,
        "sequential_alpha_effective": alpha_eff_seq,
        "holdout_id": holdout_id,
        "holdout_retired": retired,
        "holdout_uses_after": prior_uses + (1 if consumed else 0),
        "verdicts": verdicts,
        "promotion_candidates": candidates,
    }


def main(argv: Optional[list[str]] = None) -> int:
    """CLI — `python -m nuri.quant.validation.champion_gate <action>`.

    history [--family F]  attempt 원장 최근 20행
    status  [--family F]  다음 캠페인 alpha / holdout 소진 현황
    """
    import argparse

    parser = argparse.ArgumentParser(description="champion-challenger gate (#1307)")
    parser.add_argument("action", choices=["history", "status"])
    parser.add_argument("--family", default=FAMILY_VARIANT)
    args = parser.parse_args(argv)

    if args.action == "history":
        rows = query(
            """SELECT campaign_seq, challenger, verdict, p_value, alpha_spent,
                      holdout_consumed, code_rev, created_at
               FROM challenger_attempts WHERE family = ?
               ORDER BY campaign_seq DESC, challenger LIMIT 20""",
            (args.family,),
        )
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
    else:
        gate = _load_gate_config()
        seq = next_campaign_seq(args.family)
        hid = f"{gate['holdout_version']}:{args.family}"
        uses = holdout_uses(args.family, hid)
        print(
            json.dumps(
                {
                    "family": args.family,
                    "next_campaign_seq": seq,
                    "next_campaign_alpha": campaign_alpha(float(gate["alpha_total"]), seq),
                    "holdout_id": hid,
                    "holdout_uses": uses,
                    "holdout_max_uses": int(gate["holdout_max_uses"]),
                    "holdout_retired": uses >= int(gate["holdout_max_uses"]),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
