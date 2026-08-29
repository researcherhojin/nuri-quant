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
        # 호출자 params 는 그대로 왕복한다 — 귀속은 컬럼이 canonical (#1305).
        assert bt["params"] == {"top_n": 5, "rebalance_days": 20}

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

    def test_every_row_carries_the_code_revision_that_produced_it(self, client):
        """행이 어느 코드로 만들어졌는지 말할 수 있어야 한다 (#1115).

        `backtests.id=3` 은 `p_value: 0.169` 를 담고 있고, 6시간 31분 뒤 커밋 `84a5e36` 이
        그 값을 철회했다(permutation null 퇴화, 정정값 0.791). **정정된 run 은 저장되지
        않았고** strategy_id 마다 행이 정확히 1개라 밀어낼 신규 행도 없어서, 이 엔드포인트가
        지금도 철회된 숫자를 현재 증거로 내보낸다.

        낡은 행 자체보다, 망가진 코드의 산출물과 멀쩡한 산출물을 **구분할 수 없다**는 게
        문제다. 리비전이 붙으면 소비자가 "이 행은 null 수정 이전"이라고 말할 수 있다.
        """
        save_backtest(
            strategy_id="attributed",
            start_date="2026-01-01",
            end_date="2026-02-01",
            total_return=1.0,
            sharpe=1.0,
            max_drawdown=-1.0,
            win_rate=50.0,
        )
        bt = client.get("/api/research/backtests").json()["backtests"][0]

        assert bt["code_rev"], "행에 코드 리비전이 없다 — 산출 코드를 특정할 수 없다"
        # 표면은 컬럼 하나 (#1305) — params 에는 더 이상 없다 (split-brain 방지).
        assert "code_rev" not in bt["params"]
        assert bt["execution_config_sha_v1"], "행이 산출 설정을 특정하지 못한다"

    def test_a_caller_cannot_forge_the_revision(self, client):
        """호출자가 params 에 넣은 `code_rev` 는 데이터일 뿐 귀속이 아니다 (#1305).

        귀속은 자기신고가 아니다 — 컬럼은 실측값이고, 리더는 컬럼이 있으면 params 를
        보지 않는다 (legacy fallback 은 컬럼 NULL 인 전-#1305 행 전용).
        """
        save_backtest(
            strategy_id="forged",
            start_date="2026-01-01",
            end_date="2026-02-01",
            total_return=1.0,
            sharpe=1.0,
            max_drawdown=-1.0,
            win_rate=50.0,
            params={"code_rev": "deadbeef"},
        )
        bt = client.get("/api/research/backtests").json()["backtests"][0]

        assert bt["code_rev"] != "deadbeef"
        assert bt["params"]["code_rev"] == "deadbeef"  # 호출자 데이터는 손대지 않는다

    def test_a_row_written_before_attribution_reads_as_unattributed(self, client):
        """귀속 도입 이전 행은 `code_rev: None` 이다 — 그게 정보다.

        11개 기존 행이 여기 해당한다. `None` 이 "알 수 없음" 을 정직하게 말해야지,
        키가 없어서 소비자가 눈치채지 못하면 안 된다.
        """
        from nuri.core.db import get_db

        save_backtest(
            strategy_id="legacy",
            start_date="2026-01-01",
            end_date="2026-02-01",
            total_return=1.0,
            sharpe=1.0,
            max_drawdown=-1.0,
            win_rate=50.0,
        )
        with get_db() as conn:  # 귀속 이전 상태 재현 — 컬럼과 params 양쪽을 비운다
            conn.execute(
                "UPDATE backtests SET params = '{}', code_rev = NULL, "
                "execution_config_sha_v1 = NULL WHERE strategy_id = 'legacy'"
            )

        bt = client.get("/api/research/backtests").json()["backtests"][0]

        assert "code_rev" in bt, "키 자체가 없으면 소비자가 미귀속을 구분 못 한다"
        assert bt["code_rev"] is None
        assert bt["execution_config_sha_v1"] is None

    def test_a_pre_1305_row_falls_back_to_the_params_revision(self, client):
        """#1115~#1305 사이 행: 컬럼 NULL + params 안에만 code_rev — fallback 으로 읽는다.

        이 fallback 이 없으면 컬럼 도입이 기존 귀속 정보를 소비자 시야에서 지운다.
        """
        from nuri.core.db import get_db

        save_backtest(
            strategy_id="pre1305",
            start_date="2026-01-01",
            end_date="2026-02-01",
            total_return=1.0,
            sharpe=1.0,
            max_drawdown=-1.0,
            win_rate=50.0,
        )
        with get_db() as conn:
            conn.execute(
                'UPDATE backtests SET params = \'{"code_rev": "84a5e36"}\', '
                "code_rev = NULL WHERE strategy_id = 'pre1305'"
            )

        bt = client.get("/api/research/backtests").json()["backtests"][0]

        assert bt["code_rev"] == "84a5e36"

    def test_limit_clamped_high(self, client):
        assert client.get("/api/research/backtests?limit=999").status_code == 422

    def test_limit_clamped_low(self, client):
        assert client.get("/api/research/backtests?limit=0").status_code == 422

    def test_null_params_degrades_to_empty(self, client):
        # save_backtest 는 항상 "{}" 를 쓰지만, 향후/수동 writer 가 params=NULL 행을
        # 남길 수 있다. 엔드포인트는 NULL → {} 로 방어 (_loads `if not raw` 경로).
        from nuri.core.db import get_db

        with get_db() as conn:
            conn.execute(
                """INSERT INTO backtests
                   (strategy_id, start_date, end_date, total_return, sharpe,
                    max_drawdown, win_rate, params, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("S", "2026-01-01", "2026-02-01", 1.0, 0.5, -2.0, 50.0, None, "2026-06-05 00:00:00"),
            )
        bt = client.get("/api/research/backtests").json()["backtests"][0]
        assert bt["params"] == {}


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
