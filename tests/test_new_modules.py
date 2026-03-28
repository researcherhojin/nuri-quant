"""신규 모듈 테스트 — price_targets, rebalance_advisor, evidence_charts."""
import pytest

from nuri.core.db import init_db


@pytest.fixture
def db_path(tmp_path):
    """격리된 테스트 DB."""
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _seed_portfolio(db_path, holdings=None):
    """테스트 포트폴리오 데이터 삽입."""
    from nuri.core.db import get_db

    if holdings is None:
        holdings = [
            ("test", "TSLA", 33, 200.0, "USD", "SectorA"),
            ("test", "NVDA", 20, 100.0, "USD", "Semiconductor"),
            ("test", "GOOGL", 5, 269.91, "USD", "BigTech"),
            ("test", "TSLL", 96, 20.0, "USD", "SectorB"),
            ("test", "LLY", 1, 1087.10, "USD", "Pharma"),
        ]
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            holdings,
        )


def _seed_prices(db_path, prices=None):
    """테스트 가격 데이터 삽입."""
    from nuri.core.db import get_db

    if prices is None:
        prices = [
            ("2026-03-27", "TSLA", 355.0, 365.0, 350.0, 360.17, 1000000),
            ("2026-03-27", "NVDA", 165.0, 170.0, 163.0, 167.99, 2000000),
            ("2026-03-27", "GOOGL", 270.0, 278.0, 268.0, 274.26, 500000),
            ("2026-03-27", "TSLL", 11.0, 12.0, 10.5, 11.44, 300000),
            ("2026-03-27", "LLY", 880.0, 895.0, 875.0, 888.34, 100000),
        ]
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO prices (date, ticker, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            prices,
        )


def _seed_fundamentals(db_path, data=None):
    """펀더멘탈 데이터 삽입."""
    from nuri.core.db import get_db

    if data is None:
        data = [
            ("2026-03-27", "TSLA", 327.0),
            ("2026-03-27", "NVDA", 37.0),
            ("2026-03-27", "GOOGL", 22.0),
            ("2026-03-27", "LLY", 43.0),
        ]
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO fundamentals (date, ticker, pe_ratio) VALUES (?, ?, ?)",
            data,
        )


def _seed_estimates(db_path, data=None):
    """애널리스트 목표가 삽입."""
    from nuri.core.db import get_db

    if data is None:
        data = [
            ("2026-03-27", "TSLA", 393.51),
            ("2026-03-27", "NVDA", 273.61),
            ("2026-03-27", "GOOGL", 376.57),
        ]
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO estimates (date, ticker, target_mean) VALUES (?, ?, ?)",
            data,
        )


# ═══════════════════════════════════════════════════════
# Price Targets 테스트
# ═══════════════════════════════════════════════════════
class TestClassifyStockType:
    """종목 유형 분류 테스트."""

    def test_growth_by_pe(self, db_path):
        """PE > 30이면 성장주로 분류."""
        _seed_portfolio(db_path)
        _seed_fundamentals(db_path, [("2026-03-27", "TSLA", 327.0)])

        from nuri.trading.recommend.price_targets import classify_stock_type

        result = classify_stock_type("TSLA", db_path=db_path)
        assert result == "growth"

    def test_growth_by_sector(self, db_path):
        """섹터가 성장 섹터이면 PE 없어도 성장주."""
        _seed_portfolio(db_path, [
            ("test", "XYZ", 10, 100.0, "USD", "AI/Cloud"),
        ])
        from nuri.trading.recommend.price_targets import classify_stock_type

        result = classify_stock_type("XYZ", db_path=db_path)
        assert result == "growth"

    def test_value_by_low_pe(self, db_path):
        """PE < 30이고 비성장 섹터면 가치주."""
        _seed_portfolio(db_path, [
            ("test", "GOOGL", 5, 270.0, "USD", "BigTech"),
        ])
        _seed_fundamentals(db_path, [("2026-03-27", "GOOGL", 22.0)])

        from nuri.trading.recommend.price_targets import classify_stock_type

        result = classify_stock_type("GOOGL", db_path=db_path)
        assert result == "value"

    def test_value_when_no_data(self, db_path):
        """데이터 없으면 기본 가치주."""
        from nuri.trading.recommend.price_targets import classify_stock_type

        result = classify_stock_type("UNKNOWN", db_path=db_path)
        assert result == "value"


class TestCalculateTargets:
    """가격 타겟 계산 테스트."""

    def test_growth_targets(self, db_path):
        """성장주 타겟: -7% 손절, +20%/+40% 익절."""
        _seed_portfolio(db_path)
        _seed_prices(db_path)
        _seed_fundamentals(db_path)

        from nuri.trading.recommend.price_targets import calculate_targets

        result = calculate_targets("TSLA", entry_price=360.0, stock_type="growth", db_path=db_path)

        assert result["stock_type"] == "growth"
        assert result["stop_loss"] == pytest.approx(360.0 * 0.93, rel=0.01)
        assert result["target_1"] == pytest.approx(360.0 * 1.20, rel=0.01)
        assert result["target_2"] == pytest.approx(360.0 * 1.40, rel=0.01)
        assert result["target_1_sell_pct"] == 50
        assert result["target_2_sell_pct"] == 25
        assert result["trailing_stop_pct"] == -15

    def test_value_targets(self, db_path):
        """가치주 타겟: -10% 손절, +15%/+30% 익절."""
        _seed_portfolio(db_path)
        _seed_prices(db_path)

        from nuri.trading.recommend.price_targets import calculate_targets

        result = calculate_targets("GOOGL", entry_price=270.0, stock_type="value", db_path=db_path)

        assert result["stock_type"] == "value"
        assert result["stop_loss"] == pytest.approx(270.0 * 0.90, rel=0.01)
        assert result["target_1"] == pytest.approx(270.0 * 1.15, rel=0.01)
        assert result["target_2"] == pytest.approx(270.0 * 1.30, rel=0.01)

    def test_swing_targets(self, db_path):
        """스윙 타겟: -7% 손절, +5%/+10% 익절."""
        _seed_prices(db_path)

        from nuri.trading.recommend.price_targets import calculate_targets

        result = calculate_targets("NVDA", entry_price=168.0, stock_type="swing", db_path=db_path)

        assert result["stock_type"] == "swing"
        assert result["target_1"] == pytest.approx(168.0 * 1.05, rel=0.01)
        assert result["target_2"] == pytest.approx(168.0 * 1.10, rel=0.01)

    def test_analyst_target_included(self, db_path):
        """애널리스트 목표가가 있으면 포함."""
        _seed_prices(db_path)
        _seed_estimates(db_path)

        from nuri.trading.recommend.price_targets import calculate_targets

        result = calculate_targets("NVDA", entry_price=168.0, stock_type="growth", db_path=db_path)

        assert result["analyst_target"] == pytest.approx(273.61, rel=0.01)
        assert result["analyst_upside_pct"] is not None
        assert result["analyst_upside_pct"] > 0

    def test_no_price_returns_error(self, db_path):
        """가격 데이터 없으면 에러 반환."""
        from nuri.trading.recommend.price_targets import calculate_targets

        result = calculate_targets("NOPRICE", db_path=db_path)
        assert "error" in result

    def test_uses_current_price_when_no_entry(self, db_path):
        """entry_price 미지정 시 현재가 사용."""
        _seed_prices(db_path)

        from nuri.trading.recommend.price_targets import calculate_targets

        result = calculate_targets("TSLA", stock_type="growth", db_path=db_path)

        assert result["entry_price"] == result["current_price"]


class TestPortfolioTargets:
    """포트폴리오 전체 타겟 계산 테스트."""

    def test_all_holdings_have_targets(self, db_path):
        """모든 보유 종목에 대해 타겟 생성."""
        _seed_portfolio(db_path)
        _seed_prices(db_path)
        _seed_fundamentals(db_path)

        from nuri.trading.recommend.price_targets import calculate_portfolio_targets

        targets = calculate_portfolio_targets(db_path=db_path)

        assert len(targets) > 0
        tickers = {t["ticker"] for t in targets if "error" not in t}
        assert "TSLA" in tickers
        assert "NVDA" in tickers

    def test_empty_portfolio(self, db_path):
        """빈 포트폴리오면 빈 리스트."""
        from nuri.trading.recommend.price_targets import calculate_portfolio_targets

        targets = calculate_portfolio_targets(db_path=db_path)
        assert targets == []


class TestFormatTargetTree:
    """출력 포맷 테스트."""

    def test_usd_format(self):
        """USD 종목 포맷."""
        from nuri.trading.recommend.price_targets import format_target_tree

        target = {
            "ticker": "NVDA",
            "stock_type": "growth",
            "current_price": 168.0,
            "entry_price": 165.0,
            "stop_loss": 153.45,
            "stop_loss_pct": -7.0,
            "target_1": 198.0,
            "target_1_pct": 20.0,
            "target_1_sell_pct": 50,
            "target_2": 231.0,
            "target_2_pct": 40.0,
            "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": 273.61,
            "analyst_upside_pct": 63.4,
        }
        output = format_target_tree(target)

        assert "NVDA" in output
        assert "성장주" in output
        assert "$168.00" in output
        assert "손절가" in output
        assert "1차 익절" in output
        assert "50% 매도" in output

    def test_krw_format(self):
        """KRW 종목 포맷 (₩ 기호 사용)."""
        from nuri.trading.recommend.price_targets import format_target_tree

        target = {
            "ticker": "005930.KS",
            "stock_type": "growth",
            "current_price": 179700.0,
            "entry_price": 55000.0,
            "stop_loss": 55521.0,
            "stop_loss_pct": -7.0,
            "target_1": 71640.0,
            "target_1_pct": 20.0,
            "target_1_sell_pct": 50,
            "target_2": 83580.0,
            "target_2_pct": 40.0,
            "target_2_sell_pct": 25,
            "trailing_stop_pct": -15.0,
            "analyst_target": None,
            "analyst_upside_pct": None,
        }
        output = format_target_tree(target)

        assert "005930.KS" in output
        assert "₩" in output


# ═══════════════════════════════════════════════════════
# Rebalance Advisor 테스트
# ═══════════════════════════════════════════════════════
class TestDetectViolations:
    """규칙 위반 감지 테스트."""

    def test_leverage_etf_detected(self, db_path):
        """레버리지 ETF 보유 감지 (mock analyze_portfolio)."""
        from unittest.mock import patch

        import pandas as pd

        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "TSLL", "sector": "SectorB", "quantity": 96,
             "avg_price": 20.0, "current_price": 11.44, "currency": "USD",
             "current_value_usd": 1098.24, "cost_basis_usd": 1625.28,
             "pnl_usd": -527.04, "pnl_pct": -32.4, "weight_pct": 5.0, "price_date": "2026-03-27"},
            {"account": "test", "ticker": "NVDA", "sector": "Semiconductor", "quantity": 20,
             "avg_price": 100.0, "current_price": 167.99, "currency": "USD",
             "current_value_usd": 3359.8, "cost_basis_usd": 2642.8,
             "pnl_usd": 717.0, "pnl_pct": 27.1, "weight_pct": 10.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 4458.04

        from nuri.analysis.rebalance_advisor import detect_violations

        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations(db_path=db_path)

        leverage_violations = [v for v in violations if v["violation_type"] == "leverage_etf"]

        assert len(leverage_violations) >= 1
        assert leverage_violations[0]["ticker"] == "TSLL"
        assert leverage_violations[0]["action"] == "SELL_ALL"
        assert leverage_violations[0]["severity"] == "critical"

    def test_stop_loss_exceeded(self, db_path):
        """손절선 초과 감지 (mock analyze_portfolio)."""
        from unittest.mock import patch

        import pandas as pd

        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "BADSTOCK", "sector": "Test", "quantity": 10,
             "avg_price": 100.0, "current_price": 80.0, "currency": "USD",
             "current_value_usd": 800.0, "cost_basis_usd": 1000.0,
             "pnl_usd": -200.0, "pnl_pct": -20.0, "weight_pct": 100.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 800.0

        from nuri.analysis.rebalance_advisor import detect_violations

        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations(db_path=db_path)

        stop_violations = [v for v in violations if v["violation_type"] == "stop_loss_exceeded"]
        assert len(stop_violations) >= 1
        assert stop_violations[0]["ticker"] == "BADSTOCK"
        assert stop_violations[0]["action"] == "SELL_ALL"

    def test_position_limit_exceeded(self, db_path):
        """비중 한도 초과 감지 (mock analyze_portfolio)."""
        from unittest.mock import patch

        import pandas as pd

        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "TSLA", "sector": "SectorA", "quantity": 100,
             "avg_price": 350.0, "current_price": 360.0, "currency": "USD",
             "current_value_usd": 36000.0, "cost_basis_usd": 35000.0,
             "pnl_usd": 1000.0, "pnl_pct": 2.9, "weight_pct": 95.0, "price_date": "2026-03-27"},
            {"account": "test", "ticker": "NVDA", "sector": "Semiconductor", "quantity": 1,
             "avg_price": 160.0, "current_price": 168.0, "currency": "USD",
             "current_value_usd": 168.0, "cost_basis_usd": 160.0,
             "pnl_usd": 8.0, "pnl_pct": 5.0, "weight_pct": 5.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 36168.0

        from nuri.analysis.rebalance_advisor import detect_violations

        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations(db_path=db_path)

        pos_violations = [v for v in violations if v["violation_type"] == "position_limit_exceeded"]
        assert len(pos_violations) >= 1
        assert pos_violations[0]["ticker"] == "TSLA"
        assert pos_violations[0]["action"] == "REDUCE"
        assert pos_violations[0]["sell_shares"] > 0

    def test_no_violations(self, db_path):
        """규칙 준수 포트폴리오면 빈 리스트 (비중 15% 미만, 섹터 35% 미만)."""
        from unittest.mock import patch

        import pandas as pd

        # 10종목 각 10% → 단일종목 15% 미만, 같은 섹터 없음
        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "NVDA", "sector": "Semiconductor", "quantity": 1,
             "avg_price": 160.0, "current_price": 168.0, "currency": "USD",
             "current_value_usd": 168.0, "cost_basis_usd": 160.0,
             "pnl_usd": 8.0, "pnl_pct": 5.0, "weight_pct": 10.0, "price_date": "2026-03-27"},
            {"account": "test", "ticker": "GOOGL", "sector": "BigTech", "quantity": 1,
             "avg_price": 260.0, "current_price": 274.0, "currency": "USD",
             "current_value_usd": 274.0, "cost_basis_usd": 260.0,
             "pnl_usd": 14.0, "pnl_pct": 5.4, "weight_pct": 10.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 442.0

        from nuri.analysis.rebalance_advisor import detect_violations

        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            violations = detect_violations(db_path=db_path)

        assert len(violations) == 0


class TestCalculateRebalanceActions:
    """리밸런스 액션 계산 테스트."""

    def test_sorted_by_priority(self, db_path):
        """위반이 우선순위 순으로 정렬."""
        from unittest.mock import patch

        import pandas as pd

        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "TSLL", "sector": "SectorB", "quantity": 96,
             "avg_price": 20.0, "current_price": 11.44, "currency": "USD",
             "current_value_usd": 1098.24, "cost_basis_usd": 1625.28,
             "pnl_usd": -527.04, "pnl_pct": -32.4, "weight_pct": 5.0, "price_date": "2026-03-27"},
            {"account": "test", "ticker": "BADSTOCK", "sector": "Test", "quantity": 10,
             "avg_price": 100.0, "current_price": 80.0, "currency": "USD",
             "current_value_usd": 800.0, "cost_basis_usd": 1000.0,
             "pnl_usd": -200.0, "pnl_pct": -20.0, "weight_pct": 5.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 1898.24

        from nuri.analysis.rebalance_advisor import calculate_rebalance_actions

        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            actions = calculate_rebalance_actions(db_path=db_path)

        if len(actions) >= 2:
            priorities = [a["priority"] for a in actions]
            assert priorities == sorted(priorities)

    def test_total_recovery_calculated(self, db_path):
        """총 회수 금액 합산."""
        from unittest.mock import patch

        import pandas as pd

        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "TSLL", "sector": "SectorB", "quantity": 96,
             "avg_price": 20.0, "current_price": 11.44, "currency": "USD",
             "current_value_usd": 1098.24, "cost_basis_usd": 1625.28,
             "pnl_usd": -527.04, "pnl_pct": -32.4, "weight_pct": 100.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 1098.24

        from nuri.analysis.rebalance_advisor import calculate_rebalance_actions

        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            actions = calculate_rebalance_actions(db_path=db_path)

        assert len(actions) > 0
        total = sum(a["sell_value_usd"] for a in actions)
        assert total > 0


class TestGenerateAdvisorReport:
    """리포트 생성 테스트."""

    def test_report_structure(self, db_path):
        """리포트에 필수 필드 존재."""
        from unittest.mock import patch

        import pandas as pd

        mock_df = pd.DataFrame([
            {"account": "test", "ticker": "TSLL", "sector": "SectorB", "quantity": 96,
             "avg_price": 20.0, "current_price": 11.44, "currency": "USD",
             "current_value_usd": 1098.24, "cost_basis_usd": 1625.28,
             "pnl_usd": -527.04, "pnl_pct": -32.4, "weight_pct": 5.0, "price_date": "2026-03-27"},
        ])
        mock_df.attrs["total_value_usd"] = 1098.24

        from nuri.analysis.rebalance_advisor import generate_advisor_report

        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            report = generate_advisor_report(db_path=db_path)

        assert "actions" in report
        assert "total_violations" in report
        assert "total_recovery_usd" in report
        assert "violations_by_type" in report
        assert "violations_by_severity" in report
        assert "has_critical" in report

    def test_empty_portfolio_report(self, db_path):
        """빈 포트폴리오 리포트."""
        from unittest.mock import patch

        import pandas as pd

        mock_df = pd.DataFrame()

        from nuri.analysis.rebalance_advisor import generate_advisor_report

        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio", return_value=mock_df):
            report = generate_advisor_report(db_path=db_path)

        assert report["total_violations"] == 0
        assert report["total_recovery_usd"] == 0


# ═══════════════════════════════════════════════════════
# Evidence Charts 테스트
# ═══════════════════════════════════════════════════════
class TestEvidenceCharts:
    """증거 차트 생성 테스트."""

    def test_portfolio_heatmap(self, db_path, tmp_path):
        """포트폴리오 히트맵 생성."""
        _seed_portfolio(db_path)
        _seed_prices(db_path)

        from nuri.analysis.evidence_charts import generate_portfolio_heatmap

        output_dir = tmp_path / "evidence"
        output_dir.mkdir()

        result = generate_portfolio_heatmap(output_dir, db_path=db_path)
        assert result.exists()
        assert result.suffix == ".html"

    def test_fear_greed_chart(self, db_path, tmp_path):
        """Fear & Greed 차트 생성."""
        from nuri.core.db import get_db

        with get_db(db_path) as conn:
            for i in range(30):
                conn.execute(
                    "INSERT OR REPLACE INTO macro (date, indicator, value) VALUES (?, 'fear_greed', ?)",
                    (f"2026-03-{i + 1:02d}", 10.0 + i * 2),
                )

        from nuri.analysis.evidence_charts import generate_fear_greed_chart

        output_dir = tmp_path / "evidence"
        output_dir.mkdir()

        result = generate_fear_greed_chart(output_dir, db_path=db_path)
        assert result.exists()

    def test_sell_evidence_chart(self, tmp_path):
        """매도 근거 차트 생성."""
        violations = [
            {"ticker": "TSLL", "violation_type": "leverage_etf", "severity": "critical",
             "current_value": -32.3, "sell_value_usd": 1100, "action": "SELL_ALL",
             "reason": "레버리지 ETF 금지"},
            {"ticker": "OKLO", "violation_type": "stop_loss_exceeded", "severity": "critical",
             "current_value": -59.9, "sell_value_usd": 1011, "action": "SELL_ALL",
             "reason": "손절 -59.9% 초과"},
        ]

        from nuri.analysis.evidence_charts import generate_sell_evidence_chart

        output_dir = tmp_path / "evidence"
        output_dir.mkdir()

        result = generate_sell_evidence_chart(violations, output_dir)
        assert result.exists()
        content = result.read_text()
        assert "TSLL" in content

    def test_signal_performance_empty(self, db_path, tmp_path):
        """스코어카드 없으면 빈 차트."""
        from nuri.analysis.evidence_charts import generate_signal_performance_chart

        output_dir = tmp_path / "evidence"
        output_dir.mkdir()

        result = generate_signal_performance_chart(output_dir, db_path=db_path)
        assert result.exists()
