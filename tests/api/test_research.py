"""Endpoint lock-tests for /api/research/* (P1a 검증 창고 read).

- 빈 테이블 → {backtests:[], count:0} / {runs:[], count:0}
- save_backtest 1행 → /research/backtests 가 그대로 surface (params JSON 파싱)
- log_walkforward_run 1행 → /research/walkforward 가 aggregate 만 surface (folds 생략)
- limit clamp (Query le=200)

seed 는 db_path 없이 writer 호출 — client 픽스처가 DB_PATH 를 monkeypatch 하므로
앱이 읽는 동일 DB 에 기록된다 (test_alpha 패턴과 동일).
"""

from nuri.core.db import log_walkforward_run, save_backtest


class TestBacktestsEndpoint:
    def test_empty(self, client):
        r = client.get("/api/research/backtests")
        assert r.status_code == 200
        assert r.json() == {"backtests": [], "count": 0}

    def test_returns_saved_row_with_parsed_params(self, client):
        save_backtest(
            strategy_id="Momentum Top-5",
            start_date="2026-01-02",
            end_date="2026-03-31",
            total_return=12.3,
            sharpe=1.4,
            max_drawdown=-8.0,
            win_rate=55.0,
            params={"top_n": 5, "rebalance_days": 20},
        )
        data = client.get("/api/research/backtests").json()
        assert data["count"] == 1
        bt = data["backtests"][0]
        assert bt["strategy_id"] == "Momentum Top-5"
        assert bt["start_date"] == "2026-01-02"
        assert bt["total_return"] == 12.3
        assert bt["params"] == {"top_n": 5, "rebalance_days": 20}  # JSON 파싱됨

    def test_newest_first(self, client):
        for i in range(3):
            save_backtest(
                strategy_id=f"S{i}",
                start_date="2026-01-01",
                end_date="2026-02-01",
                total_return=float(i),
                sharpe=0.0,
                max_drawdown=0.0,
                win_rate=0.0,
            )
        data = client.get("/api/research/backtests").json()
        assert [b["strategy_id"] for b in data["backtests"]] == ["S2", "S1", "S0"]

    def test_limit_clamped_high(self, client):
        assert client.get("/api/research/backtests?limit=999").status_code == 422

    def test_limit_clamped_low(self, client):
        assert client.get("/api/research/backtests?limit=0").status_code == 422


class TestWalkforwardEndpoint:
    def test_empty(self, client):
        r = client.get("/api/research/walkforward")
        assert r.status_code == 200
        assert r.json() == {"runs": [], "count": 0}

    def test_returns_run_with_aggregate_only(self, client):
        log_walkforward_run(
            run_id="wf_test_1",
            model_id="m1",
            fold_spec={"kind": "rolling", "train_size": 100, "test_size": 20, "step": 20},
            metrics={"aggregate": {"sharpe_mean": 0.8, "sharpe_std": 0.1}, "folds": [{"fold": 0}]},
            pit_hash="abc",
            n_folds=3,
            n_train_obs=300,
            n_test_obs=60,
            finished_at="2026-06-05 00:00:00",
        )
        data = client.get("/api/research/walkforward").json()
        assert data["count"] == 1
        run = data["runs"][0]
        assert run["run_id"] == "wf_test_1"
        assert run["model_id"] == "m1"
        assert run["n_folds"] == 3
        # aggregate 만 surface, 폴드별 상세 생략
        assert run["aggregate"] == {"sharpe_mean": 0.8, "sharpe_std": 0.1}
        assert "folds" not in run

    def test_malformed_metrics_json_degrades_to_empty_aggregate(self, client):
        # 직접 INSERT 로 잘못된 metrics_json 주입 → 엔드포인트가 빈 dict 로 방어
        from nuri.core.db import get_db

        with get_db() as conn:
            conn.execute(
                """INSERT INTO walkforward_runs
                   (run_id, model_id, fold_spec_json, metrics_json, pit_hash, n_folds)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("wf_bad", "m2", "{}", "not-json{", "h", 1),
            )
        run = client.get("/api/research/walkforward").json()["runs"][0]
        assert run["aggregate"] == {}
