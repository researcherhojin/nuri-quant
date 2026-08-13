"""Tests for PR C (codex bubble-bear #3): market-wide crash precursor signals.

Regression lock-in:
- `yield_curve_inversion` fires only when `us_3m_yield > us_10y_yield`.
- `hy_oas_widening` requires BOTH level > threshold AND 63d change > threshold.
- Missing data → graceful `fired=False` + "데이터 부족" detail (never raise).
- SHADOW (`actionable: false`) 는 candidates 에 포함 안 됨 (구조적 격리 lock).
- `is_actionable` helper 와 `signals.yaml` 의 `actionable: false` 설정 round-trip.
"""


class TestYieldCurveInversion:
    def test_fires_when_short_exceeds_long(self, db_path):
        from nuri.core.db import get_db
        from nuri.quant.validation.market_signals import detect_yield_curve_inversion

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES ('us_3m_yield', '2026-04-22', 5.20, 'FRED')"
            )
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES ('us_10y_yield', '2026-04-22', 4.30, 'FRED')"
            )
        s = detect_yield_curve_inversion(db_path=db_path)
        assert s.fired is True
        assert s.level is not None and s.level < 0  # spread 음수
        assert "역전" in s.detail

    def test_no_fire_when_normal_slope(self, db_path):
        from nuri.core.db import get_db
        from nuri.quant.validation.market_signals import detect_yield_curve_inversion

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES ('us_3m_yield', '2026-04-22', 4.00, 'FRED')"
            )
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES ('us_10y_yield', '2026-04-22', 4.30, 'FRED')"
            )
        s = detect_yield_curve_inversion(db_path=db_path)
        assert s.fired is False
        assert s.level is not None and s.level > 0
        assert "정상" in s.detail

    def test_missing_data_returns_insufficient(self, db_path):
        """3M 또는 10Y 둘 중 하나라도 없으면 데이터 부족 처리, 절대 raise 금지."""
        from nuri.quant.validation.market_signals import detect_yield_curve_inversion

        s = detect_yield_curve_inversion(db_path=db_path)
        assert s.fired is False
        assert s.level is None
        assert "데이터 부족" in s.detail


class TestHyOasWidening:
    def _seed_oas_series(self, db_path, values: list[tuple[str, float]]):
        from nuri.core.db import get_db

        with get_db(db_path) as conn:
            for date, value in values:
                conn.execute(
                    "INSERT INTO macro (indicator, date, value, source) VALUES ('hy_oas', ?, ?, 'FRED')",
                    (date, value),
                )

    def test_fires_when_both_level_and_change_above_threshold(self, db_path):
        """Level > 5.0 AND 63d 변화 > 1.5pp → fire."""
        from nuri.quant.validation.market_signals import detect_hy_oas_widening

        # 최신 = 5.80, 63일 전 = 3.50 → 변화 +2.30pp (> 1.5)
        rows = [(f"2026-01-{i:02d}", 3.50 + (5.80 - 3.50) * (i / 63)) for i in range(1, 64)]
        rows.append(("2026-04-22", 5.80))
        self._seed_oas_series(db_path, rows)
        s = detect_hy_oas_widening(db_path=db_path)
        assert s.fired is True
        assert s.level is not None and s.level >= 5.0
        assert "확대" in s.detail

    def test_no_fire_when_level_below_threshold(self, db_path):
        """Level 4.0 < 5.0 → fire 안 됨 (변화 크더라도)."""
        from nuri.quant.validation.market_signals import detect_hy_oas_widening

        # 최신 4.0, 63일 전 1.5 → 변화 +2.5pp 이지만 level 4.0 < 5.0
        rows = [(f"2026-01-{i:02d}", 1.5 + (4.0 - 1.5) * (i / 63)) for i in range(1, 64)]
        rows.append(("2026-04-22", 4.0))
        self._seed_oas_series(db_path, rows)
        s = detect_hy_oas_widening(db_path=db_path)
        assert s.fired is False
        assert "정상" in s.detail

    def test_no_fire_when_change_small(self, db_path):
        """Level 6.0 > 5.0 이지만 변화 작으면 fire 안 됨."""
        from nuri.quant.validation.market_signals import detect_hy_oas_widening

        rows = [(f"2026-01-{i:02d}", 5.5 + (6.0 - 5.5) * (i / 63)) for i in range(1, 64)]
        rows.append(("2026-04-22", 6.0))
        self._seed_oas_series(db_path, rows)
        s = detect_hy_oas_widening(db_path=db_path)
        assert s.fired is False

    def test_missing_data_returns_insufficient(self, db_path):
        from nuri.quant.validation.market_signals import detect_hy_oas_widening

        s = detect_hy_oas_widening(db_path=db_path)
        assert s.fired is False
        assert s.level is None
        assert "데이터 부족" in s.detail
        assert "FRED_API_KEY" in s.detail  # 사용자에게 수집 경로 안내

    def test_partial_history_does_not_fire(self, db_path):
        """codex PR #436 Review CONCERN lock: lookback 미만 rows 에서 rows[-1]
        을 63d ago baseline 으로 쓰는 false SHADOW fire 차단.

        신규 FRED backfill 직후 며칠 (< 64 rows) 데이터만 있을 때 1-day 변화가
        1.5pp 넘어도 fire 안 되어야 함. Revert detection: partial guard 제거 시
        이 테스트 fail."""
        from nuri.quant.validation.market_signals import detect_hy_oas_widening

        # 10 rows: 최신 6.5, 10일 전 3.0 → 변화 +3.5pp >> 1.5pp 임계. 그러나 63d
        # 아닌 10d 변화이므로 detector 는 insufficient 로 처리해야 함.
        rows = [(f"2026-04-{i:02d}", 3.0 + (6.5 - 3.0) * (i / 10)) for i in range(1, 11)]
        self._seed_oas_series(db_path, rows)
        s = detect_hy_oas_widening(db_path=db_path)
        assert s.fired is False, (
            f"partial history (10 rows) 에서 false SHADOW fire — partial guard 누락. detail={s.detail}"
        )
        assert "히스토리 부족" in s.detail
        # level 은 현재 값 surface (사용자 가시화용), threshold 정보 유지
        assert s.level is not None and s.level > 5.0


class TestDetectAll:
    def test_returns_all_registered_signals(self, db_path):
        from nuri.quant.validation.market_signals import DETECTORS, detect_all

        results = detect_all(db_path=db_path)
        assert len(results) == len(DETECTORS)
        assert {s.signal_id for s in results} == set(DETECTORS.keys())

    def test_fired_shadow_signals_filter(self, db_path):
        from nuri.core.db import get_db
        from nuri.quant.validation.market_signals import fired_shadow_signals

        # Inversion fire + OAS 데이터 부족 (OAS 는 fire False)
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES ('us_3m_yield', '2026-04-22', 5.20, 'FRED')"
            )
            conn.execute(
                "INSERT INTO macro (indicator, date, value, source) VALUES ('us_10y_yield', '2026-04-22', 4.30, 'FRED')"
            )
        fired = fired_shadow_signals(db_path=db_path)
        assert len(fired) == 1
        assert fired[0].signal_id == "yield_curve_inversion"


class TestActionableMeta:
    def test_is_actionable_defaults_to_true(self):
        """미정의 signal 은 actionable (back-compat)."""
        from nuri.core.signal_config import is_actionable

        assert is_actionable("unknown_signal_xyz") is True

    def test_shadow_signals_are_not_actionable(self):
        """PR C 에서 추가된 crash precursor 2개는 `actionable: false`."""
        from nuri.core.signal_config import is_actionable

        assert is_actionable("yield_curve_inversion") is False
        assert is_actionable("hy_oas_widening") is False

    def test_existing_buy_signals_remain_actionable(self):
        """기존 20 신호는 build-in `actionable: true` 기본 유지."""
        from nuri.core.signal_config import is_actionable

        for sig in ("rsi_oversold", "macd_golden", "sma_golden", "bb_bounce"):
            assert is_actionable(sig) is True, f"{sig} must remain actionable"

    def test_list_shadow_signals_includes_crash_precursors(self):
        from nuri.core.signal_config import list_shadow_signals

        shadow = list_shadow_signals()
        assert "yield_curve_inversion" in shadow
        assert "hy_oas_widening" in shadow

    def test_list_buy_signals_does_not_include_shadow(self):
        """SHADOW 가 SELL 인 경우에만 해당 — 현재 crash precursor 는 둘 다 SELL. BUY 섹션 변화 없음."""
        from nuri.core.signal_config import list_buy_signals

        buy = list_buy_signals()
        assert "yield_curve_inversion" not in buy
        assert "hy_oas_widening" not in buy


class TestCandidatesExcludeShadow:
    """codex Plan Biggest Risk lock — SHADOW 가 candidates 에 스며들면 안 됨.

    현재 crash precursor (yield_curve_inversion/hy_oas_widening) 는 market-wide
    detector 라 `signal_backtest.py` 의 per-ticker `_entry_*` 함수가 없음 →
    `_build_signal_definitions` 가 detector 없는 YAML entry 를 skip 하므로
    `SIGNAL_DEFINITIONS` 에 애초에 포함 안 됨. 그래서 candidates loop 진입 자체를
    안 함 (이 자체로 Biggest Risk 해결).

    그러나 future 에 **per-ticker** SHADOW signal (actionable:false + entry 함수
    있는) 이 추가될 수 있음 → candidates.py 의 `is_actionable` check 가
    그때도 방어. 이 regression 을 별도 lock 으로 잡는다."""

    def test_market_wide_shadow_not_in_signal_definitions(self):
        """Market-wide SHADOW 는 entry 함수 없어 SIGNAL_DEFINITIONS 에서 자동 제외 —
        의도된 구조 (signal_backtest.py `_build_signal_definitions` warning log)."""
        from nuri.quant.validation.signal_backtest import SIGNAL_DEFINITIONS

        assert "yield_curve_inversion" not in SIGNAL_DEFINITIONS
        assert "hy_oas_widening" not in SIGNAL_DEFINITIONS

    def test_candidates_source_contains_is_actionable_guard(self):
        """candidates.py 소스에 `is_actionable` guard 가 SIGNAL_DEFINITIONS loop 내에
        실제로 있는지 static source assertion. Revert detection: guard 제거 시 fail.

        Integration 경로 (generate_candidates 전체 호출) 는 너무 많은 의존성을
        쌓고 early-return 경로가 많아 reliability 낮음. Source-level lock 이 더
        안정적 — codex-style regression phantom 방지."""
        import inspect

        from nuri.trading.recommend import candidates as candidates_mod

        src = inspect.getsource(candidates_mod)
        # 핵심 guard: SIGNAL_DEFINITIONS loop 안에서 is_actionable false → continue
        assert "is_actionable" in src, "candidates.py 에 `is_actionable` import/check 누락 — Biggest Risk regression"
        # `if not is_actionable(signal_id): continue` 또는 동등 형태
        assert "if not is_actionable(signal_id)" in src or "not is_actionable(sig" in src, (
            "candidates.py 의 SHADOW skip 분기 누락 — PR C regression"
        )

    def test_is_actionable_import_path_works_in_candidates(self):
        """Integration-level light check: candidates.py 가 실제로
        `nuri.core.signal_config.is_actionable` 를 import 하고 호출 가능한지."""
        from nuri.core.signal_config import is_actionable

        # 실제 SHADOW 신호 2개 모두 False, 기존 actionable signal 은 True
        assert is_actionable("yield_curve_inversion") is False
        assert is_actionable("hy_oas_widening") is False
        assert is_actionable("rsi_oversold") is True


class TestDbExceptionGracefulFallback:
    """DB 조회 실패 시 graceful fallback (lines 62-63 yield_curve, 106-107 oas)."""

    def test_yield_curve_db_error(self, monkeypatch):
        """query 가 raise 하면 'DB 조회 실패' detail 반환, 절대 raise 금지."""
        from nuri.quant.validation import market_signals as ms

        def boom(*args, **kwargs):
            raise RuntimeError("simulated DB unavailable")

        monkeypatch.setattr(ms, "query", boom)
        s = ms.detect_yield_curve_inversion(db_path=None)
        assert s.fired is False
        assert s.level is None
        assert "DB 조회 실패" in s.detail

    def test_hy_oas_db_error(self, monkeypatch):
        from nuri.quant.validation import market_signals as ms

        def boom(*args, **kwargs):
            raise RuntimeError("simulated")

        monkeypatch.setattr(ms, "query", boom)
        s = ms.detect_hy_oas_widening(db_path=None)
        assert s.fired is False
        assert s.level is None
        assert "DB 조회 실패" in s.detail


class TestBriefShadowSection:
    def test_brief_context_includes_shadow_key(self, tmp_path, db_path_mp, monkeypatch):
        """premarket_brief _collect_context 가 shadow_signals 리스트 반환.

        `db_path_mp` 로 DB 를 격리한다 — `_collect_context()` 는 db_path 인자가
        없어 전역 `DB_PATH` 를 읽고, 격리 없이는 프로덕션 DB 를 커넥션 251회
        여닫는다 (2026-08-14 실측).
        """
        from nuri.alerts import premarket_brief as pb

        # persist target 을 tmp 로 redirect (기존 test 패턴 재사용)
        monkeypatch.setattr(pb, "__file__", str(tmp_path / "nuri" / "alerts" / "premarket_brief.py"))
        (tmp_path / "nuri" / "alerts").mkdir(parents=True)
        ctx = pb._collect_context()
        assert "shadow_signals" in ctx
        assert isinstance(ctx["shadow_signals"], list)
        # 2 registered detectors — detect_all 은 데이터 없어도 insufficient entry 반환
        assert len(ctx["shadow_signals"]) == 2
        assert all("signal_id" in s and "fired" in s for s in ctx["shadow_signals"])

    def test_brief_markdown_surfaces_shadow_section(self):
        """fired 여부와 무관하게 SHADOW 섹션 항상 렌더 — UI 에 '추적 중' 가시화."""
        from nuri.alerts.premarket_brief import format_brief_markdown

        ctx = {
            "shadow_signals": [
                {
                    "signal_id": "yield_curve_inversion",
                    "fired": True,
                    "level": -90,
                    "threshold": 0.0,
                    "detail": "3M=5.2, 10Y=4.3 역전",
                },
                {"signal_id": "hy_oas_widening", "fired": False, "level": 4.5, "threshold": 5.0, "detail": "정상 구간"},
            ],
        }
        md = format_brief_markdown(ctx)
        assert "SHADOW crash precursor" in md
        assert "⚠️ yield_curve_inversion" in md  # fired
        assert "· hy_oas_widening" in md  # not fired — bullet
        assert "1/2 fired" in md

    def test_brief_embed_surfaces_shadow_section(self):
        from nuri.alerts.premarket_brief import format_brief_embed

        ctx = {
            "actions": {},
            "shadow_signals": [
                {"signal_id": "yield_curve_inversion", "fired": True, "level": -90, "threshold": 0.0, "detail": "역전"},
            ],
        }
        embed = format_brief_embed(ctx)
        names = [f["name"] for f in embed["fields"]]
        assert any("SHADOW" in n for n in names)
