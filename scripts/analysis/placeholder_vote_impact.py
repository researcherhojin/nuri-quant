"""자리표시자 verdict 가 가중 투표에서 차지하는 몫과 그것을 뺐을 때의 판정 변화 (#1437).

`#1436` 은 자리표시자를 **보고 축**(동의율 · 패널 커버리지 · 거부권 가용성)에서만 뺐다.
채점 축은 그대로 두었는데, 거기를 고치는 것은 기록 정정이 아니라 **매매 판단 변경**이라
`docs/STRATEGY.md §2.6` 기준 근거가 선행해야 하기 때문이다. 결정은 하지 않고
**아무것도 바꾸지 않는다.**

## 이 스크립트가 재는 것 — 판정 축 하나뿐

원장을 재생해 **자리표시자를 가중 투표에서 뺐을 때 `final_action` 이 몇 건, 어느 방향으로
바뀌는가**를 낸다. 그게 전부다.

그 수는 **점 추정이 아니라 상한**이다. #1436 이전에는 `_safe_query` 가 예외를 빈 결과로
삼켜 조회 **실패**와 **부재**가 같은 문구·같은 확신도로 기록됐다 — 원장만 보고 가를 수 없고,
실패였던 것을 기권으로 세면 뺄 표가 실제보다 많아진다. 잔차의 방향은 한쪽(과대)이고 크기는
모른다. 그리고 이 편향은 뒤집힘 수 하나가 아니라 **V0' 를 기준으로 삼는 모든 수**(표 비중 ·
V0' 분포 · |Δ confidence| · 귀속)에 같이 실린다.

**하류 노출(어느 화면·경로까지 닿는가)과 수익 축(그 변화가 이로웠는가)은 여기서 재지 않는다.**
둘 다 시도했다가 세 라운드 연속 틀렸다 — 게이트 목록은 세 번 다 빠진 곳이 있었고(스윙 진입만 →
`api/routes/` 두 모듈 누락 → 선행 필터 미독해로 6 배 과대), 벤치마크는 두 번 다 자산군을
잘못 묶었다. 그 조사 결과는 이슈 #1437 의 코멘트에 남아 있고, 거기서 나온 프로덕션 결함은
#1459 로 분리했다. 이 파일에는 **세 라운드 모두 그대로 재현된 축만** 남긴다.

따라서 이 산출물은 **변경을 정당화하는 데 쓸 수 없다.** "얼마나 바뀌는가" 는 말하지만
"바뀌는 게 나은가" 는 말하지 않는다. §2.6 승격에는 별도 근거가 필요하다.

## 설계 원칙 두 가지

**채점 커널을 복사하지 않는다.** 변형은 전부 `_build_consensus` 의 **입력**에서 만든다.
사본을 두면 원본이 바뀔 때 조용히 드리프트해 측정이 거짓말을 시작한다.

**재구성은 스스로를 검증하지 못한다.** 과거 행에는 `abstained` 플래그가 없어(#1436 이
2026-09-07 머지) 생산 지점의 자리표시자 문구로 되짚는다. 재생이 persist 된 판정을 재현하는지는
`replay_matches_ledger` 가 보지만 **그 일치는 분류의 근거가 아니다**: `abstained` 는 V0 의
`final_action` 에 애초에 영향이 없다(그게 #1437 이 미뤄진 이유다). 분류 검증은 현재 코드를
실제로 돌려 생산 플래그와 대조하는 별도 축이며
`tests/scripts/test_placeholder_vote_impact.py::TestClassifyMatchesProduction` 이 잠근다.

## 세 축

| | 뜻 |
|---|---|
| `V0` | 원장 그대로. persist 된 판정과 대조해 재생 충실도를 본다 |
| `V0'` | 같은 행을 **현재 코드**로 재채점. #1436 이 `fundamental` 자리표시자 확신도를 50 → 0 으로 바꿨으므로, 이 분리 없이는 이미 고쳐진 몫까지 #1437 의 효과로 청구하게 된다 |
| `V1` | 자리표시자를 가중 투표에서 완전히 제외 |

`V2`(본문의 "중간안" — 방향은 안 밀되 분모는 유지)는 `final_action` 이 V1 과 **같다**. 분모는
argmax 를 바꾸지 않는다. 즉 판정 축에서는 중간 지점이 아니고, 확신도만 달라진다.

⚠️ **프로덕션 수정은 이 스크립트의 구성을 베끼면 안 된다.** 여기서는 자리표시자를 커널
**입력에서** 빼는데, 그러면 커널 안에서 `verdicts == live` 가 되어 `panel_coverage=1.0` ·
`abstained_agents=[]` 가 되고 `contributions` 에서 자리표시자 행이 사라진다 — 즉 #1436 이
만든 보고 축이 조용히 되돌아간다. 실제 수정은 **`action_scores` 루프에서만** 건너뛰어야 한다.

사용:
    .venv/bin/python scripts/analysis/placeholder_vote_impact.py
    .venv/bin/python scripts/analysis/placeholder_vote_impact.py --db /path/to.db
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import json
import re
import sys
from pathlib import Path

from nuri.trading.agents.base import AgentVerdict
from nuri.trading.agents.consensus.scoring import _build_consensus

# 생산 지점이 내는 자리표시자 문구. **현재 소스 + 과거 변형** 둘 다 담는다 — `fundamental` 은
# 지금 "펀더멘탈 데이터 제한적" 이지만 #1436 이전 원장 486 셀은 "데이터 제한적" 이다. 현재
# 소스만 보고 매핑하면 그 셀을 통째로 놓치고, 그게 확신도 50 짜리 최대 기여 중 하나였다.
PLACEHOLDER_REASONS: dict[str, set[str]] = {
    "crypto": {"크립토 데이터 없음", "크립토 변동 없음"},
    "fundamental": {"펀더멘탈 데이터 없음", "펀더멘탈 데이터 제한적", "데이터 제한적"},
    # ⚠️ `"Korean market neutral"`(#1436 이전 폴백, 원장 16 셀)은 **일부러 안 넣는다.**
    # 자리표시자처럼 읽히지만 실측상 16 셀 전부 `fx_rate` 와 `momentum_20d` 를 담고 있어,
    # 현재 부재 게이트 기준으로는 **값을 읽고 중립을 확인한 판단**이다. 넣으면 `fundamental`
    # 에서 codex R9 가 잡은 과교정 — 진짜 판정을 자리표시자로 깎기 — 을 그대로 반복한다.
    "korean_market": {"US ticker — Korean market agent neutral", "한국 시장 데이터 없음"},
    # `"레짐/매크로 데이터 부족"` 은 #1436 이전의 레짐 산출 불가 경로다. 현재 코드는 그 자리를
    # `"레짐/매크로 조회 실패"`(degraded)로 가르지만 원장에서는 둘을 구분할 수 없다. 확신도가
    # 양쪽 다 0.0 이라 어느 축에 놓든 채점에 기여하지 않으므로 기권으로 둔다.
    "macro": {"SPY 데이터 부족", "레짐/매크로 데이터 부족"},
    "options": {"PCR 데이터 없음", "PCR 값 없음"},
    "retail": {"리테일 센티먼트 데이터 없음", "리테일 데이터 부족"},
    "smart_money": {"스마트머니 데이터 없음"},
    "technical": {"데이터 부족"},
    "wallstreet": {"Wall Street 데이터 미지원 종목", "Wall Street 데이터 부족"},
}

# `smart_money` 의 자리표시자는 **고정 문구가 아니다** — `"; ".join(notes) or "스마트머니
# 데이터 없음"` 이고 각 note 에 날짜가 박힌다 (`슈퍼투자자 13F 낡음(최신 2026-01-02) — 제외`).
# 집합으로는 영영 못 담으므로 모양으로 본다. 이걸 빠뜨리면 #1187 이 일부러 만든 분기가
# **확신도 30 짜리 살아 있는 HOLD** 로 집계된다 — `fundamental "데이터 제한적"` 과 같은 형태다.
STALE_NOTE = re.compile(r"낡음\(최신 [^)]*\)\s*—\s*제외$")

# 실패(degraded) — 러너가 만드는 것 + 각 에이전트의 `failed_reason`. 러너의 예외 문구는
# `f"에러: {e}"` 라 접두사로 본다.
DEGRADED_REASONS = {
    "타임아웃",
    "가격 조회 실패",
    "레짐/매크로 조회 실패",
    "리스크 조회 실패",
    "리테일 조회 실패",
    "스마트머니 조회 실패",
    "크립토 조회 실패",
    "펀더멘탈 조회 실패",
    "한국 시장 조회 실패",
    "yfinance 로드 실패",
    "PCR 조회 실패",
    "Wall Street 조회 실패",
}
DEGRADED_PREFIX = "에러:"

# #1436 이 확신도를 바꾼 **관측 가능한** 기권 지점.
#
# ⚠️ "나머지는 플래그만 붙었다" 는 문자 그대로는 참이 아니다. `_no_data` 의 실패 분기도
# 확신도를 0 으로 깎으므로, #1436 이전에 **조회가 실패해서** 난 자리표시자는 현재 코드라면
# 0 점이다. 그런데 그 시절엔 `_safe_query` 가 예외를 빈 결과로 삼켜 부재와 실패가 같은 문구·
# 같은 확신도로 기록됐다 — 원장만 보고는 가를 수 없다. 방향은 뒤집힘 수를 부풀리는 쪽이고
# 크기는 알 수 없다. **측정되지 않은 잔차로 남겨 두고 보고서에 그렇게 적는다.**
CURRENT_CODE_ZEROED = {("fundamental", "데이터 제한적")}

# #1436 머지일. 이 **다음날부터의** 결정만이 부재와 실패를 갈라 기록하므로, 위 잔차를
# 실측으로 가둘 수 있는 유일한 표본이다. 보고서가 그 표본이 몇 건인지 적는다 — 0 이면
# 잔차는 영영 미관측이고 그 사실 자체가 결과의 일부다.
#
# 경계에서 머지일 **당일은 제외한다**(`>` 이지 `>=` 가 아니다). 원장은 시각 없이 날짜만
# 담는데 PR #1449 는 2026-09-07T11:49Z = 20:49 KST 에 머지됐고 consensus cron 은 07:05 KST 다
# — 그날 결정은 옛 코드가 낸 것이다. 넣으면 사후 표본을 실제보다 많이 세어 "잔차를 가둘 수
# 있다" 를 과장한다.
FIX_MERGED = "2026-09-07"

# 과거 "데이터 제한적" 폴백이 소비하던 필드. 하나라도 값이 있으면 **실제 데이터로 중립을
# 확인한 판단**이라 기권이 아니다 (#1436 codex R9 가 잡은 축).
FUNDAMENTAL_FIELDS = ("pe", "roe", "growth", "debt")


def classify(verdict: dict) -> tuple[bool, bool]:
    """persist 된 verdict dict → `(degraded, abstained)`.

    확신도로 파생하지 않는다 — `normalize_confidence` 가 낮은 원점수를 0 으로 깎아
    `risk` 의 "리스크 정상"(평가해서 위험 없음을 확인한 판단) 같은 진짜 판정을 기권으로
    뒤집는다 (#1436 codex R1).
    """
    agent = verdict.get("agent_name")
    reason = (verdict.get("reasoning") or "").strip()
    if reason.startswith(DEGRADED_PREFIX) or reason in DEGRADED_REASONS:
        return True, False
    if agent == "smart_money" and reason and all(STALE_NOTE.search(s.strip()) for s in reason.split(";")):
        return False, True  # 전 소스가 낡아 제외됐다 — 근거 0 으로 낸 자리표시자
    if reason in PLACEHOLDER_REASONS.get(agent, frozenset()):
        if (agent, reason) in CURRENT_CODE_ZEROED:
            points = verdict.get("data_points") or {}
            if any(points.get(k) is not None for k in FUNDAMENTAL_FIELDS):
                return False, False  # 값이 있었다 — 중립을 확인한 판단이지 부재가 아니다
        return False, True
    return False, False


def to_verdict(verdict: dict) -> AgentVerdict:
    degraded, abstained = classify(verdict)
    return AgentVerdict(
        agent_name=verdict["agent_name"],
        ticker=verdict.get("ticker", ""),
        action=verdict["action"],
        confidence=float(verdict.get("confidence") or 0),
        reasoning=verdict.get("reasoning") or "",
        data_points=verdict.get("data_points") or {},
        alpha_action=verdict.get("alpha_action"),
        portfolio_action=verdict.get("portfolio_action"),
        degraded=degraded,
        abstained=abstained,
    )


def as_current_code(verdict: AgentVerdict) -> AgentVerdict:
    """persist 된 verdict 를 **현재 코드가 냈을 값**으로 옮긴다. 두 지점이다.

    **degraded 는 전부 0.** `base.py::_no_data` 의 실패 분기가 `confidence` 인자를 의도적으로
    버리고(#1436 codex R6), 러너가 만드는 degraded 도 처음부터 0 이다. 즉 오늘의 코드에서
    실패한 조회는 어떤 경로로도 표를 못 던진다 — 원장에 확신도가 남아 있는 degraded 행을
    그대로 두면 V0' 가 "현재 코드" 를 참칭한다.

    **관측 가능한 기권 지점(`CURRENT_CODE_ZEROED`)만 0.** `classify` 가 data_points 를 보고
    **살아 있는 판단**이라고 판정한 legacy `fundamental` 행까지 깎으면 그 판단을 지우는 것이다.
    """
    if verdict.degraded:
        return dataclasses.replace(verdict, confidence=0.0)
    if (verdict.agent_name, verdict.reasoning) in CURRENT_CODE_ZEROED and verdict.abstained:
        return dataclasses.replace(verdict, confidence=0.0)
    return verdict


@dataclasses.dataclass
class RowResult:
    """한 결정의 세 축 재채점 결과."""

    date: str
    ticker: str
    ledger_action: str
    ledger_confidence: float
    current_action: str
    excluded_action: str
    current_confidence: float
    excluded_confidence: float
    middle_confidence: float
    placeholder_share: float
    sole_flippers: list[str]
    placeholder_agents: list[str]
    live_panel: int
    panel: int

    @property
    def flipped_vs_ledger(self) -> bool:
        return self.excluded_action != self.ledger_action

    @property
    def flipped(self) -> bool:
        """현재 코드 기준 뒤집힘 — 이 이슈의 순효과."""
        return self.excluded_action != self.current_action


def rescore(row: dict) -> RowResult | None:
    """한 행을 세 축으로 재채점. `scoring_detail` 이 consensus 스키마가 아니면 None."""
    try:
        raw = json.loads(row["agent_verdicts"])
        detail = json.loads(row["scoring_detail"])
    except (TypeError, ValueError):
        return None
    weights = detail.get("weights")
    if not weights or detail.get("source") != "consensus":
        return None

    verdicts = [to_verdict(v) for v in raw]
    current = [as_current_code(v) for v in verdicts]
    live = [v for v in verdicts if not v.degraded and not v.abstained]
    if not live:
        # 전 패널이 자리표시자면 커널의 `max()` 가 전부 0 인 dict 에서 삽입 순서로 "BUY" 를
        # 뽑아 **없던 뒤집힘을 만들어낸다.** 측정 대상이 아니라 보고할 사실이다.
        return None

    ledger = _build_consensus(row["ticker"], verdicts, weights)
    v_current = _build_consensus(row["ticker"], current, weights)
    v_excluded = _build_consensus(row["ticker"], live, weights)

    total_current = sum(v_current.scoring_detail["action_scores"].values())
    total_excluded = sum(v_excluded.scoring_detail["action_scores"].values())
    # V2 (중간안) — 분자는 자리표시자 없이, 분모는 그대로. 방향은 V1 과 같고 확신도만 희석된다.
    # **커널과 같은 자리에서 반올림한다**: 프로덕션이 `round(x, 1)` 한 값을 비교하므로, raw 로
    # 두면 두 변형을 서로 다르게 반올림된 수로 비교하게 된다.
    middle = (
        v_excluded.scoring_detail["action_scores"][v_excluded.final_action] / total_current * 100
        if total_current > 0
        else 0.0
    )

    # 귀속: 표를 던지는 자리표시자를 **하나씩만** 빼도 뒤집히는지 — 에이전트별 민감도.
    # degraded 는 여기서 따로 안 본다: `as_current_code` 가 이미 전부 0 으로 옮겼으므로
    # 현재 코드 기준으로 표를 던지는 자리표시자는 **기권뿐**이다.
    voting = [v for v in current if v.abstained and v.confidence > 0]
    sole = [
        v.agent_name
        for v in voting
        if _build_consensus(row["ticker"], [x for x in current if x is not v], weights).final_action
        != v_current.final_action
    ]

    return RowResult(
        date=row["date"],
        ticker=row["ticker"],
        ledger_action=ledger.final_action,
        ledger_confidence=ledger.final_confidence,
        current_action=v_current.final_action,
        excluded_action=v_excluded.final_action,
        current_confidence=v_current.final_confidence,
        excluded_confidence=v_excluded.final_confidence,
        middle_confidence=round(middle, 1),
        placeholder_share=((total_current - total_excluded) / total_current) if total_current > 0 else 0.0,
        sole_flippers=sole,
        placeholder_agents=[v.agent_name for v in voting],
        live_panel=len(live),
        panel=len(verdicts),
    )


def replay_matches_ledger(row: dict, result: RowResult) -> bool:
    """재생이 persist 된 판정을 재현하는가 — **action 과 confidence 둘 다**.

    action 만 보면 3 지 선다라 우연 일치가 흔하다. 허용 오차 0.15 는 커널이 4 자리에서
    반올림해 저장한 것과 재계산값의 알려진 차이다.

    ⚠️ 이건 **가중치·verdict 복원**의 검증이지 분류의 검증이 아니다. 모듈 독스트링 참조.
    """
    if result.ledger_action != row["action"]:
        return False
    return abs(result.ledger_confidence - float(row["confidence"] or 0)) <= 0.15


def load_rows(db_path=None) -> list[dict]:
    from nuri.core.db import query

    return [
        dict(r)
        for r in query(
            "SELECT date, ticker, action, confidence, agent_verdicts, scoring_detail FROM recommendations "
            "WHERE agent_verdicts IS NOT NULL AND scoring_detail IS NOT NULL ORDER BY date, ticker",
            db_path=db_path,
        )
    ]


def _quantiles(values: list[float]) -> tuple[float, float, float]:
    if not values:
        return (0.0, 0.0, 0.0)
    s = sorted(values)
    return (s[len(s) // 2], s[min(len(s) - 1, int(0.95 * len(s)))], s[-1])


def format_report(results: list[RowResult], *, mismatched: int) -> str:
    out: list[str] = []
    n = len(results)
    out.append(f"재현된 결정 {n} 건 ({results[0].date} ~ {results[-1].date}) · 재현 실패 {mismatched} 건")

    med, p95, mx = _quantiles([r.placeholder_share for r in results])
    out.append(f"자리표시자 표 비중 (현재 코드): 중앙값 {med:.1%} · p95 {p95:.1%} · 최대 {mx:.1%}")
    for label, key in (("V0' 현재 코드", "current_action"), ("V1  자리표시자 제외", "excluded_action")):
        dist = collections.Counter(getattr(r, key) for r in results)
        out.append(f"  {label}: " + " · ".join(f"{k} {v}" for k, v in sorted(dist.items())))

    ledger_flips = [r for r in results if r.flipped_vs_ledger]
    flips = [r for r in results if r.flipped]
    out.append(
        f"뒤집힘 — 원장 기준 {len(ledger_flips)} / {n} · "
        f"**현재 코드 기준 {len(flips)} / {n}** (순효과, **상한** — 아래 잔차 항)"
    )
    for (a, b), c in collections.Counter((r.current_action, r.excluded_action) for r in flips).most_common():
        out.append(f"    {a} → {b}: {c}")

    med, _, mx = _quantiles([abs(r.excluded_confidence - r.current_confidence) for r in results])
    out.append(f"|Δ final_confidence| V1: 중앙값 {med:.2f} · 최대 {mx:.2f}")
    med, _, mx = _quantiles([abs(r.middle_confidence - r.current_confidence) for r in results])
    out.append(f"|Δ final_confidence| V2: 중앙값 {med:.2f} · 최대 {mx:.2f}")
    if flips:
        # V1 에서 확신도가 오르는 이유는 신호가 아니라 **분모 축소**다. 얇은 패널일수록 크다 —
        # 그 사실 없이 확신도만 보면 "제외하니 더 확신하게 됐다" 로 읽힌다.
        sizes = collections.Counter(r.live_panel for r in flips)
        thin = sum(c for s, c in sizes.items() if s <= 3)
        out.append(
            f"  뒤집힌 행의 live 패널 분포 {dict(sorted(sizes.items()))} — "
            f"그중 ≤3 인 것 {thin} 건. V1 확신도 상승분은 분모 축소이지 신호가 아니다"
        )

    appear = collections.Counter(a for r in flips for a in r.placeholder_agents)
    out.append("뒤집힌 행에서 표를 던진 자리표시자: " + " · ".join(f"{k} {v}" for k, v in appear.most_common()))
    sole = collections.Counter()
    for r in flips:
        if len(r.sole_flippers) == 1:
            sole[r.sole_flippers[0]] += 1
        else:
            sole["(단독 불가)" if not r.sole_flippers else "(단독 후보 복수)"] += 1
    out.append("  하나만 빼도 뒤집힘: " + " · ".join(f"{k} {v}" for k, v in sole.most_common()))

    post_fix = sum(1 for r in results if r.date > FIX_MERGED)
    out.append(
        "⚠️ 위에서 V0' 를 기준으로 삼는 수는 **전부**(표 비중 · V0' 분포 · 뒤집힘 · "
        "|Δ confidence| · 귀속) **측정되지 않은 잔차만큼 부풀려져 있다** — #1436 이전에는 "
        "조회 실패와 부재가 같은 문구·확신도로 기록돼 원장에서 못 가른다 "
        "(`CURRENT_CODE_ZEROED` 주석). 방향은 한쪽(과대)이고 크기는 모른다: 점 추정이 아니라 상한이다."
    )
    out.append(
        f"   잔차를 가둘 표본 — #1436 머지({FIX_MERGED}) **다음날부터**의 결정 {post_fix} / {n} 건"
        + (". 표본이 전부 그 이전이라 잔차는 **미관측**이다" if post_fix == 0 else "")
    )
    out.append(
        "이 스크립트는 **판정 축만** 잰다 — 하류 노출과 수익 축은 여기서 재지 않는다 "
        "(모듈 독스트링 참조). 따라서 이 산출물로 변경을 정당화할 수 없다."
    )
    return "\n".join(out)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=None, help="DB 경로 (기본: NURI_DB_PATH / data/portfolio.db)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows = load_rows(args.db)
    if not rows:
        print("scoring_detail 을 가진 recommendations 행이 없다 — 측정할 것이 없다.", file=sys.stderr)
        return 1

    results: list[RowResult] = []
    mismatched = 0
    for row in rows:
        result = rescore(row)
        if result is None:
            continue
        if not replay_matches_ledger(row, result):
            mismatched += 1  # 재현 못 한 행으로 변화를 주장하지 않는다
            continue
        results.append(result)

    if not results:
        print("재생이 원장을 하나도 재현하지 못했다 — 측정을 신뢰할 수 없다.", file=sys.stderr)
        return 1

    print(format_report(results, mismatched=mismatched))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
