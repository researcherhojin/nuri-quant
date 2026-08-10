"""SIEGE 변동성 게이트 ↔ 수집기 계약 (#1020).

**왜 이 파일이 있나**: `config/rules.yaml siege_gates` 가 선언한 변동성 지표 중
`kospi` 와 `yield` 는 **`macro` 테이블에 한 행도 없다** (2026-08-10 프로덕션 실측
n=0). 그런데 게이트는 값이 없으면 `passed=True, "데이터 없음 — 스킵"` 을 돌려줬다.
결과: `volatility_gate_kr_index` 와 `volatility_gate_bond` 가 도입(#248) 이래
**한 번도 평가된 적 없이 매 인증서에 초록으로 찍혔다**.

⚠️ "미수집"이 아니다 — `prices.KOSPI` 는 419행, `prices.TLT` 는 46행 있다.
`_get_indicator_value` 가 **`macro` 만 읽어서** 못 보는 것이다. 그래서 이 계약의
대조 대상은 "수집 여부"가 아니라 **macro 에 쓰는 수집기 레지스트리**다.

게이트 semantics 는 고쳤지만(값 없음 → FAIL/warning) 그것만으로는 **다음 dangling
포인터를 못 막는다**. 그래서 config 를 그 레지스트리와 대조한다.

allowlist 는 양방향으로 잠근다 (`test_cross_stage_imports.py` 와 같은 관용):
새 dangling 포인터도 실패하고, 해소된 항목을 안 지워도 실패한다.
"""

from pathlib import Path

import yaml

from nuri.trading.engine.certification import _check_volatility_for_class

REPO_ROOT = Path(__file__).resolve().parents[3]

# ── 수집기가 실제로 macro 테이블에 쓰는 indicator 이름 ──
# macro.py 두 dict 가 대부분을 차지하고, 나머지는 collector 당 고정 이름.
# 새 collector 를 추가하면 여기에 등록해야 이 계약이 유효하다.
_OTHER_COLLECTORS = {
    "fear_greed": "nuri/collectors/fear_greed.py",
    "put_call_ratio": "nuri/collectors/cboe.py",
    "btc_usd_cg": "nuri/collectors/coingecko.py",
    "btc_market_cap_t": "nuri/collectors/coingecko.py",
    "btc_24h_volume_b": "nuri/collectors/coingecko.py",
    "btc_24h_change_pct": "nuri/collectors/coingecko.py",
    "btc_dominance": "nuri/collectors/coingecko.py",
    "crypto_total_mcap_t": "nuri/collectors/coingecko.py",
    "crypto_active_count": "nuri/collectors/coingecko.py",
}

# ── 선언은 됐지만 macro 에 안 들어오는 지표 ──
# 값은 "왜 아직 없는가 + 해소 조건". 비워두지 말 것 — 이유 없는 항목은 그냥
# 잊혀진 dangling 포인터다.
KNOWN_MISSING_FROM_MACRO = {
    "kospi": (
        "시계열 자체는 있다 — `prices.KOSPI` 419행 (freshness 게이트가 이미 쓴다). "
        "`_get_indicator_value` 가 macro 만 읽어서 못 볼 뿐. prices 폴백을 붙이면 "
        "해소되지만 게이트 입력 경로 변경이라 별도 이슈. threshold 5.0 은 "
        "pct-change 의미로 이미 정합이라 재도출 불필요."
    ),
    "yield": (
        "bond 클래스 primary. `macro.us_10y_yield`(335행) / `prices.TLT`(46행) 둘 다 "
        "후보지만 threshold 0.3 이 `_compute_3d_change` 의 pct 의미와 안 맞는다 "
        "(0.3% ≈ 1.3bp → 상시 발화). 포인터만 바꾸면 죽은 게이트가 시끄러운 게이트로 "
        "바뀔 뿐 — threshold 재도출은 매매 룰 변경이라 STRATEGY PR 대상."
    ),
}


def _collected_indicators() -> set[str]:
    from nuri.collectors.macro import FRED_SERIES, YFINANCE_SYMBOLS

    return set(FRED_SERIES) | set(YFINANCE_SYMBOLS) | set(_OTHER_COLLECTORS)


def _declared_indicators() -> dict[str, str]:
    """rules.yaml 이 선언한 변동성 지표 → 선언 위치. `_3d_change` 는 base 로 환원."""
    rules = yaml.safe_load((REPO_ROOT / "config" / "rules.yaml").read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for cls, policy in (rules.get("siege_gates", {}).get("asset_classes", {}) or {}).items():
        names = [policy.get("volatility_primary")] + list(policy.get("volatility_secondary") or [])
        for name in names:
            if not name:
                continue
            base = name[: -len("_3d_change")] if name.endswith("_3d_change") else name
            out.setdefault(base, f"{cls}.{name}")
    return out


class TestVolatilityGateContract:
    def test_every_declared_indicator_is_collected_or_allowlisted(self):
        declared = _declared_indicators()
        collected = _collected_indicators()
        dangling = {b: w for b, w in declared.items() if b not in collected and b not in KNOWN_MISSING_FROM_MACRO}
        assert not dangling, (
            "macro 에 안 들어오는 변동성 지표를 게이트에 선언했다 — 그 게이트는 영원히 평가되지 않는다:\n"
            + "\n".join(f"  {b}  (선언: {w})" for b, w in sorted(dangling.items()))
            + "\nmacro 수집을 붙이거나, 못 하면 KNOWN_MISSING_FROM_MACRO 에 사유와 함께 등록할 것."
        )

    def test_allowlist_has_no_stale_entries(self):
        """macro 에 들어오게 됐거나 config 에서 사라진 항목은 allowlist 에서 빼야 한다."""
        declared, collected = _declared_indicators(), _collected_indicators()
        resolved = sorted(b for b in KNOWN_MISSING_FROM_MACRO if b in collected)
        assert not resolved, f"이제 macro 에 들어온다 — KNOWN_MISSING_FROM_MACRO 에서 제거할 것: {resolved}"
        unused = sorted(b for b in KNOWN_MISSING_FROM_MACRO if b not in declared)
        assert not unused, f"config 가 더는 선언하지 않는다 — KNOWN_MISSING_FROM_MACRO 에서 제거할 것: {unused}"

    def test_allowlist_reasons_are_substantive(self):
        thin = sorted(b for b, why in KNOWN_MISSING_FROM_MACRO.items() if len(why.strip()) < 40)
        assert not thin, f"사유가 너무 짧다 (해소 조건까지 적을 것): {thin}"


class TestUnknownIndicatorFailsTheGate:
    """게이트 semantics 잠금 — 미상은 PASS 가 아니다."""

    def test_missing_primary_fails_as_warning(self, db_path):
        conds = _check_volatility_for_class(
            "bond", {"volatility_primary": "yield_3d_change", "volatility_primary_threshold": 0.3}, db_path=db_path
        )
        assert len(conds) == 1
        assert conds[0].passed is False, "값 없는 지표가 PASS 로 찍히면 죽은 게이트가 초록으로 보인다"
        assert conds[0].severity == "warning", "certified 를 막으면 안 된다 — Surface rung"
        assert "평가 불가" in conds[0].detail

    def test_present_primary_still_passes_when_calm(self, db_path):
        from nuri.core.db import upsert_macro
        from nuri.core.timezone import today_kst

        upsert_macro([{"indicator": "vix", "date": today_kst(), "value": 15.0, "source": "test"}], db_path)
        conds = _check_volatility_for_class(
            "us_equity", {"volatility_primary": "vix", "volatility_primary_threshold": 30}, db_path=db_path
        )
        assert conds[0].passed is True
        assert "정상" in conds[0].detail

    def test_breach_still_fails_as_warning(self, db_path):
        from nuri.core.db import upsert_macro
        from nuri.core.timezone import today_kst

        upsert_macro([{"indicator": "vix", "date": today_kst(), "value": 35.0, "source": "test"}], db_path)
        conds = _check_volatility_for_class(
            "us_equity", {"volatility_primary": "vix", "volatility_primary_threshold": 30}, db_path=db_path
        )
        assert conds[0].passed is False
        assert conds[0].severity == "warning"
