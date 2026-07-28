"""GET /api/alpha — 정직한 alpha 추적 (P0c).

완료/미완료 신호는 생산자(ForwardOutcomeTracker)와 동일하게 realized_return 유무.
realized_return=NULL 은 두 경우: lookahead(미도래) vs price-missing(데이터 갭) — notes 로 구분.
"""

from nuri.core.db import get_db


def _seed(conn, *, rec_id, window, alpha, rr, notes="action=BUY", decided="2026-04-01"):
    """agent_decisions(FK) + decision_outcomes 한 쌍. rr=None 이면 미완료."""
    did = f"rec_{rec_id}"
    conn.execute(
        "INSERT INTO agent_decisions "
        "(decision_id, ticker, as_of_date, action, conviction, inputs_json, rationale_json, status) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (did, f"TK{rec_id}", decided, "BUY", 0.7, "{}", "{}", "emitted"),
    )
    bench = (rr - alpha) if (rr is not None and alpha is not None) else None
    conn.execute(
        "INSERT INTO decision_outcomes "
        "(decision_id, observation_window, tracked_as_of_date, realized_return, benchmark_return, alpha, "
        "hypothesis_validation, notes) VALUES (?,?,?,?,?,?,?,?)",
        (did, window, "2026-06-04", rr, bench, alpha, "insufficient_data", notes),
    )


def test_alpha_completeness_and_quality(client):
    with get_db() as conn:
        # 완료 + clean
        _seed(conn, rec_id=100, window=7, alpha=0.05, rr=0.06)
        # 미도래 (lookahead) — notes 대문자여도 case-insensitive 분류 (codex round3 P1 잠금)
        _seed(conn, rec_id=101, window=30, alpha=None, rr=None, notes="target_date 2026-07 > today (LOOKAHEAD guard)")
        # 완료지만 suspect (|rr|>0.5 = 측정 오류 의심)
        _seed(conn, rec_id=102, window=30, alpha=0.9, rr=0.9)
        # 데이터 갭 (price missing) — rr NULL 이지만 lookahead 아님
        _seed(conn, rec_id=103, window=14, alpha=None, rr=None, notes="price missing — entry=None, exit=None")

    r = client.get("/api/alpha")
    assert r.status_code == 200
    data = r.json()

    assert data["edge_status"] == "NOT_MEASURABLE"
    assert data["data_quality"]["suspect_rows"] == 1
    assert data["data_quality"]["unmeasured_rows"] == 1  # rec_103
    # effective_bets = clean distinct 결정만 = rec_100 (suspect/미측정 제외)
    assert data["effective_bets"] == 1

    by_w = {w["window"]: w for w in data["windows"]}
    # window 7: rec_100 완료 clean
    assert by_w[7]["n_completed"] == 1
    assert by_w[7]["n_pending"] == 0
    assert by_w[7]["n_clean"] == 1
    assert by_w[7]["median_alpha_pct"] == 5.0
    # window 14: rec_103 데이터 갭
    assert by_w[14]["n_completed"] == 0
    assert by_w[14]["n_unmeasured"] == 1
    # window 30: rec_102 완료(suspect) + rec_101 미도래
    assert by_w[30]["n_completed"] == 1
    assert by_w[30]["n_pending"] == 1
    assert by_w[30]["n_unmeasured"] == 0
    assert by_w[30]["n_clean"] == 0
    assert by_w[30]["median_alpha_pct"] is None


def test_alpha_empty(client):
    """데이터 없으면 0 카운트 + NOT_MEASURABLE."""
    r = client.get("/api/alpha")
    assert r.status_code == 200
    data = r.json()
    assert data["effective_bets"] == 0
    assert data["edge_status"] == "NOT_MEASURABLE"
    assert all(w["n_completed"] == 0 and w["n_pending"] == 0 for w in data["windows"])


# ─── §3.11 실험 슬리브 사용률 (#834) ──────────────────────────────────────────


def test_alpha_exposes_sleeve_utilization(client):
    """alpha 헤드라인 옆에 "어떤 자본으로 낸 결과인가"가 같이 나온다.

    Gotcha-Test Pair: 응답에서 `sleeve` 를 빼면 FAIL — 백엔드에 계산이 있어도
    노출 지점이 없으면 사용자는 상한 초과를 못 본다.
    """
    from unittest.mock import patch

    rows = [
        {
            "account": "Brokerage Alpha",
            "strategy": "core",
            "cap_pct": 10.0,
            "sleeve_usd": 2500.0,
            "equity_usd": 10_000.0,
            "used_pct": 25.0,
            "over": True,
        }
    ]
    with patch("nuri.analysis.sleeve.sleeve_utilization", return_value=rows):
        r = client.get("/api/alpha")
    assert r.status_code == 200
    sleeve = r.json()["sleeve"]
    assert sleeve["count"] == 1
    assert sleeve["any_over"] is True
    assert sleeve["accounts"][0]["used_pct"] == 25.0


def test_alpha_sleeve_never_leaks_account_name(client):
    """계좌 키(broker name)는 응답에 들어가면 안 된다 — 전략 라벨만 (public repo/dashboard).

    Gotcha-Test Pair: row 를 통째로 응답에 실으면 FAIL.
    """
    from unittest.mock import patch

    rows = [
        {
            "account": "Brokerage Alpha",
            "strategy": "core",
            "cap_pct": 10.0,
            "sleeve_usd": 2500.0,
            "equity_usd": 10_000.0,
            "used_pct": 25.0,
            "over": True,
        }
    ]
    with patch("nuri.analysis.sleeve.sleeve_utilization", return_value=rows):
        r = client.get("/api/alpha")
    assert "Brokerage Alpha" not in r.text


def test_alpha_survives_sleeve_failure(client):
    """슬리브 계산이 터져도 alpha 헤드라인은 살아야 한다 (soft error, shape 유지)."""
    from unittest.mock import patch

    with patch("nuri.analysis.sleeve.sleeve_utilization", side_effect=RuntimeError("boom")):
        r = client.get("/api/alpha")
    assert r.status_code == 200
    data = r.json()
    assert data["edge_status"] == "NOT_MEASURABLE"  # 본 계약 유지
    assert data["sleeve"]["accounts"] == [] and "error" in data["sleeve"]
