"""Toss Open API connector lock-tests — creds 로더 + 토큰 캐시 + verify 분기.

네트워크(POST token / GET exchange-rate)는 mock. 실제 키 없이 결정적 검증.
주문 endpoint 부재(STRATEGY §7.1) 도 간접 보장 — 모듈에 order 함수 없음.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from nuri.collectors import toss


@pytest.fixture(autouse=True)
def _isolate_creds_and_cache(monkeypatch, tmp_path):
    """env creds 비우고 토큰 캐시를 tmp 로 격리 (실제 config/toss 미오염)."""
    monkeypatch.delenv("TOSS_API_KEY", raising=False)
    monkeypatch.delenv("TOSS_SECRET_KEY", raising=False)
    monkeypatch.setattr(toss, "_TOKEN_CACHE", tmp_path / "token.json")
    monkeypatch.setattr(toss, "_TOSS_DIR", tmp_path / "toss")


class TestCreds:
    def test_missing_raises(self):
        with pytest.raises(toss.TossCredentialsError):
            toss._load_creds()

    def test_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("TOSS_API_KEY", "c_test")
        monkeypatch.setenv("TOSS_SECRET_KEY", "s_test")
        assert toss._load_creds() == ("c_test", "s_test")


class TestToken:
    def test_uses_unexpired_cache(self, monkeypatch):
        # 만료 충분히 남은 캐시 → 네트워크 호출 없이 반환
        from nuri.core.timezone import kst_now

        toss._TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        toss._TOKEN_CACHE.write_text(
            json.dumps({"access_token": "cached_tok", "expires_at": kst_now().timestamp() + 99999})
        )
        with patch("requests.post") as post:
            assert toss.get_access_token() == "cached_tok"
        post.assert_not_called()

    def test_issues_and_caches_when_no_cache(self, monkeypatch):
        monkeypatch.setenv("TOSS_API_KEY", "c_test")
        monkeypatch.setenv("TOSS_SECRET_KEY", "s_test")
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"access_token": "new_tok", "token_type": "Bearer", "expires_in": 86400}
        with patch("requests.post", return_value=resp) as post:
            tok = toss.get_access_token(force=True)
        assert tok == "new_tok"
        post.assert_called_once()
        # form-encoded client_credentials 로 호출
        assert post.call_args.kwargs["data"]["grant_type"] == "client_credentials"
        # 캐시 기록됨
        assert json.loads(toss._TOKEN_CACHE.read_text())["access_token"] == "new_tok"

    def test_non200_raises(self, monkeypatch):
        monkeypatch.setenv("TOSS_API_KEY", "c_test")
        monkeypatch.setenv("TOSS_SECRET_KEY", "s_test")
        resp = MagicMock(status_code=401, text="invalid_client")
        with patch("requests.post", return_value=resp):
            with pytest.raises(toss.TossCredentialsError):
                toss.get_access_token(force=True)


class TestVerify:
    def test_missing_creds_returns_2(self, capsys):
        assert toss.verify() == 2
        assert "미설정" in capsys.readouterr().out

    def test_full_path_ok(self, monkeypatch, capsys):
        monkeypatch.setenv("TOSS_API_KEY", "c_test")
        monkeypatch.setenv("TOSS_SECRET_KEY", "s_test")
        tok_resp = MagicMock(status_code=200)
        tok_resp.json.return_value = {"access_token": "tok", "expires_in": 86400}
        fx_resp = MagicMock()
        fx_resp.raise_for_status.return_value = None
        fx_resp.json.return_value = {"result": {"rate": "1380.5", "validFrom": "2026-06-22T09:30:00+09:00"}}
        with patch("requests.post", return_value=tok_resp), patch("requests.get", return_value=fx_resp):
            rc = toss.verify()
        out = capsys.readouterr().out
        assert rc == 0
        assert "1380.5" in out and "적용 가능" in out
        # secret 이 출력에 새지 않음
        assert "s_test" not in out


def test_no_order_endpoints():
    """STRATEGY §7.1 — 모듈에 주문(create/cancel/order) 함수 부재 보장."""
    names = [n for n in dir(toss) if "order" in n.lower() or "buy" in n.lower() or "sell" in n.lower()]
    assert names == []


class TestRemaining:
    def test_creds_yaml_fallback(self, monkeypatch, tmp_path):
        # env 없고 config/toss/toss_devlp.yaml 있으면 거기서 읽음
        d = tmp_path / "toss"
        d.mkdir(parents=True, exist_ok=True)
        (d / "toss_devlp.yaml").write_text("api_key: yk\nsecret_key: ys\n")
        monkeypatch.setattr(toss, "_TOSS_DIR", d)
        assert toss._load_creds() == ("yk", "ys")

    def test_get_exchange_rate_unwraps_result(self, monkeypatch):
        from nuri.core.timezone import kst_now

        toss._TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        toss._TOKEN_CACHE.write_text(json.dumps({"access_token": "t", "expires_at": kst_now().timestamp() + 99999}))
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"result": {"rate": "1377"}}
        with patch("requests.get", return_value=resp) as get:
            fx = toss.get_exchange_rate("USD", "KRW")
        assert fx["rate"] == "1377"
        assert get.call_args.kwargs["params"] == {"baseCurrency": "USD", "quoteCurrency": "KRW"}

    def test_cli_verify_dispatch(self, monkeypatch):
        monkeypatch.setattr(toss, "verify", lambda: 0)
        assert toss.main(["--verify"]) == 0

    def test_cli_no_args_prints_help(self, capsys):
        assert toss.main([]) == 0
        assert "verify" in capsys.readouterr().out.lower()


class TestBranches:
    def test_cached_token_corrupt_returns_none(self):
        toss._TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        toss._TOKEN_CACHE.write_text("not-json{")
        assert toss._read_cached_token() is None

    def test_cached_token_expired_returns_none(self):
        from nuri.core.timezone import kst_now

        toss._TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        toss._TOKEN_CACHE.write_text(json.dumps({"access_token": "old", "expires_at": kst_now().timestamp() - 1}))
        assert toss._read_cached_token() is None

    def test_token_response_without_access_token_raises(self, monkeypatch):
        monkeypatch.setenv("TOSS_API_KEY", "c")
        monkeypatch.setenv("TOSS_SECRET_KEY", "s")
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"token_type": "Bearer"}  # access_token 없음
        with patch("requests.post", return_value=resp):
            with pytest.raises(toss.TossCredentialsError):
                toss.get_access_token(force=True)

    def test_authed_get_sends_account_header(self):
        from nuri.core.timezone import kst_now

        toss._TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        toss._TOKEN_CACHE.write_text(json.dumps({"access_token": "t", "expires_at": kst_now().timestamp() + 99999}))
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"result": {}}
        with patch("requests.get", return_value=resp) as get:
            toss._authed_get("/api/v1/holdings", {}, account_seq="acct9")
        assert get.call_args.kwargs["headers"]["X-Tossinvest-Account"] == "acct9"

    def test_verify_token_network_error_returns_2(self, monkeypatch, capsys):
        monkeypatch.setenv("TOSS_API_KEY", "c")
        monkeypatch.setenv("TOSS_SECRET_KEY", "s")
        with patch("requests.post", side_effect=RuntimeError("network down")):
            rc = toss.verify()
        assert rc == 2
        assert "오류" in capsys.readouterr().out

    def test_verify_fx_fails_after_token_ok_returns_2(self, monkeypatch, capsys):
        monkeypatch.setenv("TOSS_API_KEY", "c")
        monkeypatch.setenv("TOSS_SECRET_KEY", "s")
        tok = MagicMock(status_code=200)
        tok.json.return_value = {"access_token": "t", "expires_in": 86400}
        with patch("requests.post", return_value=tok), patch("requests.get", side_effect=RuntimeError("fx down")):
            rc = toss.verify()
        assert rc == 2
        assert "환율 조회 실패" in capsys.readouterr().out


def _seed_token(monkeypatch=None):
    """캐시 토큰 심기 — get_accounts/get_holdings 가 네트워크 토큰발급 안 하게."""
    from nuri.core.timezone import kst_now

    toss._TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    toss._TOKEN_CACHE.write_text(json.dumps({"access_token": "t", "expires_at": kst_now().timestamp() + 99999}))


class TestAccountsHoldings:
    def test_unwrap_list_variants(self):
        assert toss._unwrap_list({"result": [{"a": 1}]}, "x") == [{"a": 1}]
        assert toss._unwrap_list({"result": {"holdings": [{"a": 1}]}}, "holdings") == [{"a": 1}]
        assert toss._unwrap_list([{"a": 1}], "x") == [{"a": 1}]
        assert toss._unwrap_list({"result": {}}, "x") == []

    def test_get_accounts(self):
        _seed_token()
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"result": [{"accountSeq": "seq1", "accountType": "DOMESTIC"}]}
        with patch("requests.get", return_value=resp) as get:
            accts = toss.get_accounts()
        assert accts[0]["accountSeq"] == "seq1"
        assert get.call_args.kwargs["params"] == {}

    def test_resolve_account_seq_from_env(self, monkeypatch):
        monkeypatch.setenv("TOSS_ACCOUNT_SEQ", "envseq")
        assert toss._resolve_account_seq() == "envseq"

    def test_resolve_account_seq_explicit_arg_wins(self, monkeypatch):
        monkeypatch.setenv("TOSS_ACCOUNT_SEQ", "envseq")
        assert toss._resolve_account_seq("argseq") == "argseq"

    def test_resolve_account_seq_autodiscover(self, monkeypatch):
        monkeypatch.delenv("TOSS_ACCOUNT_SEQ", raising=False)
        with patch.object(toss, "get_accounts", return_value=[{"accountSeq": "auto1"}]):
            assert toss._resolve_account_seq() == "auto1"

    def test_resolve_account_seq_no_accounts_raises(self, monkeypatch):
        monkeypatch.delenv("TOSS_ACCOUNT_SEQ", raising=False)
        with patch.object(toss, "get_accounts", return_value=[]):
            with pytest.raises(toss.TossCredentialsError):
                toss._resolve_account_seq()

    def test_get_holdings_sends_account_header(self):
        _seed_token()
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"result": [{"symbol": "005930", "quantity": 10}]}
        with patch("requests.get", return_value=resp) as get:
            h = toss.get_holdings(account_seq="seq9")
        assert h[0]["symbol"] == "005930"
        assert get.call_args.kwargs["headers"]["X-Tossinvest-Account"] == "seq9"


class TestCoverageGaps:
    def test_get_access_token_no_cache_fetches(self, monkeypatch):
        # force=False + 캐시 부재 → _read_cached_token None(L73) → fetch 경로(95->98)
        monkeypatch.setenv("TOSS_API_KEY", "c")
        monkeypatch.setenv("TOSS_SECRET_KEY", "s")
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"access_token": "fetched", "expires_in": 86400}
        with patch("requests.post", return_value=resp):
            assert toss.get_access_token(force=False) == "fetched"

    def test_unwrap_list_non_dict_result_returns_empty(self):
        # result 가 list/dict 아님 → return [] (L149)
        assert toss._unwrap_list({"result": "notalist"}, "k") == []
        assert toss._unwrap_list({"result": None}, "k") == []
