"""KIS Open API 실시간 시세 수집기 단위 테스트.

검증 범위:
    - 자격 증명 로드 (.env 우선, yaml fallback)
    - rate limit 응답 감지 (_is_rate_limit)
    - 한국/미국 시세 파싱
    - 단일 종목 retry 로직
    - check_credentials 동작
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from nuri.collectors.kis_realtime import (
    KISCredentials,
    KISRealtimeCollector,
    _is_rate_limit,
    _is_token_cooldown,
    inquire_price_kr,
    inquire_price_us,
    load_credentials,
)

# ═══════════════════════════════════════════════════════
# KISCredentials
# ═══════════════════════════════════════════════════════


class TestKISCredentials:
    def test_is_valid_with_keys(self):
        c = KISCredentials("key", "secret", "12345678", "hts", "prod")
        assert c.is_valid() is True

    def test_is_valid_empty(self):
        c = KISCredentials("", "", "", "", "prod")
        assert c.is_valid() is False

    def test_base_url_prod(self):
        c = KISCredentials("k", "s", "", "", "prod")
        assert "openapi.koreainvestment" in c.base_url
        assert "vts" not in c.base_url

    def test_base_url_paper(self):
        c = KISCredentials("k", "s", "", "", "paper")
        assert "openapivts.koreainvestment" in c.base_url


# ═══════════════════════════════════════════════════════
# load_credentials (env vs yaml fallback)
# ═══════════════════════════════════════════════════════


class TestLoadCredentials:
    def test_env_priority(self, monkeypatch):
        monkeypatch.setenv("KIS_PROD_APP_KEY", "env_key")
        monkeypatch.setenv("KIS_PROD_APP_SECRET", "env_secret")
        monkeypatch.setenv("KIS_PROD_ACCOUNT", "11111111")
        monkeypatch.setenv("KIS_HTS_ID", "hts1")
        creds = load_credentials("prod")
        assert creds is not None
        assert creds.app_key == "env_key"
        assert creds.app_secret == "env_secret"
        assert creds.account == "11111111"
        assert creds.mode == "prod"

    def test_paper_env(self, monkeypatch):
        # prod env clear, paper env set
        monkeypatch.delenv("KIS_PROD_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_PROD_APP_SECRET", raising=False)
        monkeypatch.setenv("KIS_PAPER_APP_KEY", "paper_key")
        monkeypatch.setenv("KIS_PAPER_APP_SECRET", "paper_secret")
        creds = load_credentials("paper")
        assert creds is not None
        assert creds.app_key == "paper_key"
        assert creds.mode == "paper"

    def test_no_creds_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.delenv("KIS_PROD_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_PROD_APP_SECRET", raising=False)
        monkeypatch.delenv("KIS_PAPER_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_PAPER_APP_SECRET", raising=False)
        # YAML 경로도 격리
        with patch("nuri.collectors.kis_realtime.KIS_YAML_PATH", tmp_path / "nonexistent.yaml"):
            creds = load_credentials("prod")
            assert creds is None


# ═══════════════════════════════════════════════════════
# _is_rate_limit
# ═══════════════════════════════════════════════════════


class TestIsRateLimit:
    def test_rate_limit_msg_only(self):
        """KIS 해외 시세 API: msg_cd=None이지만 메시지로 매칭."""
        payload = {"rt_cd": "1", "msg_cd": None, "msg1": "초당 거래건수를 초과하였습니다."}
        assert _is_rate_limit(payload) is True

    def test_rate_limit_official_code(self):
        """공식 EGW00201 코드 매칭."""
        payload = {"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "rate limit"}
        assert _is_rate_limit(payload) is True

    def test_rate_limit_korean_partial(self):
        payload = {"rt_cd": "1", "msg1": "거래건수 초과"}
        assert _is_rate_limit(payload) is True

    def test_normal_response_mca00000(self):
        """정상 응답 코드는 rate limit 아님."""
        payload = {"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "정상처리 되었습니다."}
        assert _is_rate_limit(payload) is False

    def test_other_error(self):
        payload = {"rt_cd": "1", "msg_cd": "EXC00001", "msg1": "잘못된 종목코드"}
        assert _is_rate_limit(payload) is False

    def test_empty_payload(self):
        assert _is_rate_limit({}) is False
        assert _is_rate_limit(None) is False


class TestIsTokenCooldown:
    def test_403_status(self):
        assert _is_token_cooldown({}, 403) is True

    def test_200_with_cooldown_message(self):
        payload = {"error_description": "1분당 1회 발급 가능합니다."}
        assert _is_token_cooldown(payload, 200) is True

    def test_normal_200(self):
        payload = {"access_token": "abc"}
        assert _is_token_cooldown(payload, 200) is False

    def test_500_not_cooldown(self):
        assert _is_token_cooldown({}, 500) is False


# ═══════════════════════════════════════════════════════
# 시세 조회 응답 파싱
# ═══════════════════════════════════════════════════════


class TestInquirePriceKR:
    def test_successful_parse(self):
        creds = KISCredentials("k", "s", "", "", "prod")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "rt_cd": "0",
            "msg1": "정상처리 되었습니다.",
            "output": {
                "stck_prpr": "210500",
                "stck_oprc": "200000",
                "stck_hgpr": "215000",
                "stck_lwpr": "199000",
                "acml_vol": "12345678",
            },
        }
        with patch("nuri.collectors.kis_realtime.requests.get", return_value=mock_resp):
            row = inquire_price_kr(creds, "token", "005930.KS")
        assert row is not None
        assert row["ticker"] == "005930.KS"
        assert row["close"] == 210500.0
        assert row["volume"] == 12345678

    def test_empty_output_returns_none(self):
        creds = KISCredentials("k", "s", "", "", "prod")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"rt_cd": "0", "output": {}}
        with patch("nuri.collectors.kis_realtime.requests.get", return_value=mock_resp):
            row = inquire_price_kr(creds, "token", "005930.KS")
        assert row is None

    def test_rate_limit_retries_then_succeeds(self):
        """rate limit 응답 → 1초 대기 → 재시도 성공."""
        creds = KISCredentials("k", "s", "", "", "prod")
        rate_limit_resp = MagicMock(status_code=200)
        rate_limit_resp.json.return_value = {"rt_cd": "1", "msg1": "초당 거래건수 초과"}
        success_resp = MagicMock(status_code=200)
        success_resp.json.return_value = {
            "rt_cd": "0",
            "output": {"stck_prpr": "100000"},
        }
        with patch("nuri.collectors.kis_realtime.requests.get",
                   side_effect=[rate_limit_resp, success_resp]):
            with patch("nuri.collectors.kis_realtime.time.sleep"):  # sleep 우회
                row = inquire_price_kr(creds, "token", "005930.KS")
        assert row is not None
        assert row["close"] == 100000.0


class TestInquirePriceUS:
    def test_nas_first_success(self):
        creds = KISCredentials("k", "s", "", "", "prod")
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "rt_cd": "0",
            "output": {"last": "184.02", "open": "180.50", "high": "185.00",
                       "low": "179.00", "tvol": "100000000"},
        }
        with patch("nuri.collectors.kis_realtime.requests.get", return_value=mock_resp):
            with patch("nuri.collectors.kis_realtime.time.sleep"):
                row = inquire_price_us(creds, "token", "NVDA")
        assert row is not None
        assert row["close"] == 184.02

    def test_excd_fallback_nas_to_nys(self):
        """NAS 빈 응답 → NYS 시도 → 성공."""
        creds = KISCredentials("k", "s", "", "", "prod")
        nas_empty = MagicMock(status_code=200)
        nas_empty.json.return_value = {"rt_cd": "0", "output": {"last": ""}}
        nys_success = MagicMock(status_code=200)
        nys_success.json.return_value = {"rt_cd": "0", "output": {"last": "49.07"}}
        with patch("nuri.collectors.kis_realtime.requests.get",
                   side_effect=[nas_empty, nys_success]):
            with patch("nuri.collectors.kis_realtime.time.sleep"):
                row = inquire_price_us(creds, "token", "OKLO")
        assert row is not None
        assert row["close"] == 49.07

    def test_all_excd_empty_returns_none(self):
        creds = KISCredentials("k", "s", "", "", "prod")
        empty = MagicMock(status_code=200)
        empty.json.return_value = {"rt_cd": "0", "output": {"last": ""}}
        with patch("nuri.collectors.kis_realtime.requests.get", return_value=empty):
            with patch("nuri.collectors.kis_realtime.time.sleep"):
                row = inquire_price_us(creds, "token", "FAKE")
        assert row is None


# ═══════════════════════════════════════════════════════
# Collector check_credentials
# ═══════════════════════════════════════════════════════


class TestKISRealtimeCollector:
    def test_check_credentials_no_env(self, monkeypatch, tmp_path):
        monkeypatch.delenv("KIS_PROD_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_PROD_APP_SECRET", raising=False)
        with patch("nuri.collectors.kis_realtime.KIS_YAML_PATH", tmp_path / "nonexistent.yaml"):
            collector = KISRealtimeCollector(mode="prod")
            assert collector.check_credentials() is False

    def test_check_credentials_with_env(self, monkeypatch):
        monkeypatch.setenv("KIS_PROD_APP_KEY", "test_key_xxxx")
        monkeypatch.setenv("KIS_PROD_APP_SECRET", "test_secret")
        collector = KISRealtimeCollector(mode="prod")
        assert collector.check_credentials() is True

    def test_collect_returns_empty_when_no_creds(self, monkeypatch, tmp_path):
        monkeypatch.delenv("KIS_PROD_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_PROD_APP_SECRET", raising=False)
        with patch("nuri.collectors.kis_realtime.KIS_YAML_PATH", tmp_path / "nonexistent.yaml"):
            collector = KISRealtimeCollector(mode="prod")
            result = collector.collect()
            assert isinstance(result, pd.DataFrame)
            assert result.empty
