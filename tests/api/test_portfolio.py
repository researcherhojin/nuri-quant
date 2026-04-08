"""Tests for portfolio — split from test_api_all.py."""
import asyncio
import json
import time as _time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices
from tests.api._helpers import _csv_file  # noqa: F401


class TestPortfolio:
    def test_portfolio_empty(self, client):
        r = client.get("/api/portfolio")
        assert r.status_code == 200
        data = r.json()
        assert "holdings" in data
        assert "count" in data
        assert data["count"] == 0

    def test_add_holding(self, client):
        r = client.post("/api/portfolio", json={
            "account": "toss", "ticker": "AAPL",
            "quantity": 10, "avg_price": 180.0,
            "currency": "USD", "sector": "Tech",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r2 = client.get("/api/portfolio")
        assert r2.json()["count"] == 1

    def test_delete_holding(self, client):
        client.post("/api/portfolio", json={
            "account": "toss", "ticker": "AAPL",
            "quantity": 10, "avg_price": 180.0,
        })
        r = client.delete("/api/portfolio/toss/AAPL")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r2 = client.get("/api/portfolio")
        assert r2.json()["count"] == 0

    def test_delete_nonexistent(self, client):
        """존재하지 않는 종목 삭제 → 404."""
        r = client.delete("/api/portfolio/test/XXXX")
        assert r.status_code == 404

    def test_delete_invalid_account(self, client):
        """유효하지 않은 계좌명 → 400."""
        r = client.delete("/api/portfolio/fake/XXXX")
        assert r.status_code == 400

    def test_risk_graceful(self, client):
        """빈 DB에서도 에러 대신 에러 dict 반환."""
        r = client.get("/api/risk")
        assert r.status_code == 200


class TestPutEndpoint:
    def test_update_quantity(self, seeded_client):
        """수량 수정."""
        r = seeded_client.put("/api/portfolio/toss/AAPL", json={"quantity": 20})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["updated"]["quantity"] == 20

        holdings = seeded_client.get("/api/portfolio").json()["holdings"]
        assert holdings[0]["quantity"] == 20

    def test_update_avg_price(self, seeded_client):
        """평균가 수정."""
        r = seeded_client.put("/api/portfolio/toss/AAPL", json={"avg_price": 200.0})
        assert r.status_code == 200
        assert r.json()["updated"]["avg_price"] == 200.0

    def test_update_multiple_fields(self, seeded_client):
        """여러 필드 동시 수정."""
        r = seeded_client.put("/api/portfolio/toss/AAPL", json={
            "quantity": 15, "avg_price": 190.0, "sector": "BigTech",
        })
        assert r.status_code == 200
        updated = r.json()["updated"]
        assert updated["quantity"] == 15
        assert updated["avg_price"] == 190.0
        assert updated["sector"] == "BigTech"

    def test_update_nonexistent(self, client):
        """존재하지 않는 종목 수정 → 404."""
        r = client.put("/api/portfolio/test/XXXX", json={"quantity": 5})
        assert r.status_code == 404

    def test_update_empty_body(self, seeded_client):
        """변경 필드 없으면 → 400."""
        r = seeded_client.put("/api/portfolio/toss/AAPL", json={})
        assert r.status_code == 400

    def test_update_invalid_account(self, seeded_client):
        """유효하지 않은 계좌 → 400."""
        r = seeded_client.put("/api/portfolio/fake/AAPL", json={"quantity": 5})
        assert r.status_code == 400

    def test_update_invalid_quantity(self, seeded_client):
        """음수 수량 → 422."""
        r = seeded_client.put("/api/portfolio/toss/AAPL", json={"quantity": -1})
        assert r.status_code == 422


class TestPutValidation:
    """PUT 엔드포인트 경계값 검증."""

    def test_update_quantity_over_max(self, seeded_client):
        """수량 100,000 초과 → 422."""
        r = seeded_client.put("/api/portfolio/toss/AAPL", json={"quantity": 100_001})
        assert r.status_code == 422

    def test_update_avg_price_zero(self, seeded_client):
        """평균가 0 → 422."""
        r = seeded_client.put("/api/portfolio/toss/AAPL", json={"avg_price": 0})
        assert r.status_code == 422

    def test_update_avg_price_over_max(self, seeded_client):
        """평균가 10,000,000 초과 → 422."""
        r = seeded_client.put("/api/portfolio/toss/AAPL", json={"avg_price": 10_000_001})
        assert r.status_code == 422

    def test_update_sector_too_long(self, seeded_client):
        """섹터 50자 초과 → 422."""
        r = seeded_client.put("/api/portfolio/toss/AAPL", json={"sector": "A" * 51})
        assert r.status_code == 422

    def test_update_currency(self, seeded_client):
        """통화 변경."""
        r = seeded_client.put("/api/portfolio/toss/AAPL", json={"currency": "KRW"})
        assert r.status_code == 200
        assert r.json()["updated"]["currency"] == "KRW"

    def test_update_invalid_ticker_format(self, seeded_client):
        """유효하지 않은 ticker 포맷 → 400."""
        r = seeded_client.put("/api/portfolio/toss/invalid!", json={"quantity": 5})
        assert r.status_code == 400


class TestSyncErrorHandling:
    """YAML 동기화 실패 시 DB 변경 유지 확인."""

    def test_sync_failure_does_not_block_api(self, tmp_path, monkeypatch):
        """sync 실패해도 POST는 200 반환."""
        sync_db = tmp_path / "test.db"
        init_db(sync_db)

        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", sync_db)

        import nuri.core.portfolio_sync as sync_mod
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", Path("/dev/null/impossible/path.yaml"))

        from nuri.api.main import app
        c = TestClient(app)

        r = c.post("/api/portfolio", json={
            "account": "toss", "ticker": "MSFT",
            "quantity": 5, "avg_price": 400.0,
        })
        assert r.status_code == 200

        r2 = c.get("/api/portfolio")
        assert r2.json()["count"] == 1


class TestPostValidation:
    """POST 엔드포인트 HoldingInput 검증 — 경계값."""

    def test_post_invalid_ticker(self, client):
        """잘못된 ticker 포맷 → 422."""
        r = client.post("/api/portfolio", json={
            "account": "toss", "ticker": "invalid!",
            "quantity": 10, "avg_price": 100.0,
        })
        assert r.status_code == 422

    def test_post_quantity_zero(self, client):
        """수량 0 → 422."""
        r = client.post("/api/portfolio", json={
            "account": "toss", "ticker": "AAPL",
            "quantity": 0, "avg_price": 100.0,
        })
        assert r.status_code == 422

    def test_post_quantity_over_max(self, client):
        """수량 100,000 초과 → 422."""
        r = client.post("/api/portfolio", json={
            "account": "toss", "ticker": "AAPL",
            "quantity": 100_001, "avg_price": 100.0,
        })
        assert r.status_code == 422

    def test_post_avg_price_zero(self, client):
        """평균가 0 → 422."""
        r = client.post("/api/portfolio", json={
            "account": "toss", "ticker": "AAPL",
            "quantity": 10, "avg_price": 0,
        })
        assert r.status_code == 422

    def test_post_avg_price_over_max(self, client):
        """평균가 10,000,000 초과 → 422."""
        r = client.post("/api/portfolio", json={
            "account": "toss", "ticker": "AAPL",
            "quantity": 10, "avg_price": 10_000_001,
        })
        assert r.status_code == 422

    def test_post_invalid_account(self, client):
        """유효하지 않은 계좌 → 422."""
        r = client.post("/api/portfolio", json={
            "account": "fake", "ticker": "AAPL",
            "quantity": 10, "avg_price": 100.0,
        })
        assert r.status_code == 422

    def test_post_sector_too_long(self, client):
        """섹터 50자 초과 → 422."""
        r = client.post("/api/portfolio", json={
            "account": "toss", "ticker": "AAPL",
            "quantity": 10, "avg_price": 100.0,
            "sector": "A" * 51,
        })
        assert r.status_code == 422


class TestDeleteValidation:
    """DELETE 엔드포인트 경로 파라미터 검증."""

    def test_delete_invalid_ticker_format(self, client):
        """유효하지 않은 ticker 포맷 → 400."""
        r = client.delete("/api/portfolio/toss/invalid!")
        assert r.status_code == 400


class TestYamlSync:
    def test_post_syncs_yaml(self, client, tmp_path):
        """POST 후 YAML 파일 생성 확인."""
        client.post("/api/portfolio", json={
            "account": "kakaopay", "ticker": "NVDA",
            "quantity": 10, "avg_price": 130.0,
            "currency": "USD", "sector": "Semiconductor",
        })
        yaml_path = tmp_path / "portfolio.yaml"
        assert yaml_path.exists()
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        holdings = data["accounts"]["kakaopay"]["holdings"]
        assert len(holdings) == 1
        assert holdings[0]["ticker"] == "NVDA"

    def test_put_syncs_yaml(self, seeded_client, tmp_path):
        """PUT 후 YAML에 변경 반영."""
        seeded_client.put("/api/portfolio/toss/AAPL", json={"quantity": 25})
        yaml_path = tmp_path / "portfolio.yaml"
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        holdings = data["accounts"]["toss"]["holdings"]
        assert holdings[0]["qty"] == 25

    def test_delete_syncs_yaml(self, seeded_client, tmp_path):
        """DELETE 후 YAML에서 제거."""
        seeded_client.delete("/api/portfolio/toss/AAPL")
        yaml_path = tmp_path / "portfolio.yaml"
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        toss = data["accounts"].get("toss", {})
        assert "holdings" not in toss or len(toss.get("holdings", [])) == 0

    def test_load_yaml_default_path(self, tmp_path, monkeypatch):
        """_load_yaml()를 인수 없이 호출 시 CONFIG_PATH 사용."""
        import nuri.core.portfolio_sync as sync_mod
        from nuri.core.portfolio_sync import _load_yaml
        nonexistent = tmp_path / "nonexistent.yaml"
        monkeypatch.setattr(sync_mod, "CONFIG_PATH", nonexistent)
        result = _load_yaml()
        assert result == {}

    def test_preserves_metadata(self, tmp_path, monkeypatch):
        """기존 YAML 메타데이터 (name, broker 등) 보존."""
        from nuri.core.portfolio_sync import sync_portfolio_to_yaml

        yaml_db = tmp_path / "test2.db"
        init_db(yaml_db)

        yaml_path = tmp_path / "portfolio.yaml"
        existing = {
            "accounts": {
                "kakaopay": {
                    "name": "카카오페이 종합계좌",
                    "broker": "카카오페이증권",
                    "currency": "USD",
                    "total_invested": 48323344,
                    "holdings": [],
                },
            },
        }
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(existing, f, allow_unicode=True)

        upsert_portfolio([{
            "account": "kakaopay", "ticker": "TSLA",
            "quantity": 10, "avg_price": 300.0,
            "currency": "USD", "sector": "EV/AI",
        }], db_path=yaml_db)

        sync_portfolio_to_yaml(config_path=yaml_path, db_path=yaml_db)

        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        kp = data["accounts"]["kakaopay"]
        assert kp["name"] == "카카오페이 종합계좌"
        assert kp["broker"] == "카카오페이증권"
        assert kp["total_invested"] == 48323344
        assert len(kp["holdings"]) == 1
        assert kp["holdings"][0]["ticker"] == "TSLA"


class TestImport:
    """POST /api/portfolio/import tests."""

    def test_import_csv(self, client):
        """정상 CSV import."""
        csv_content = "account,ticker,quantity,avg_price,currency,sector\ntoss,AAPL,10,180.0,USD,Tech\nkakaopay,NVDA,5,130.0,USD,Semiconductor\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["imported"] == 2
        assert data["errors"] == []

        r2 = client.get("/api/portfolio")
        assert r2.json()["count"] == 2

    def test_import_minimal_columns(self, client):
        """필수 컬럼만 있는 CSV — currency/sector 기본값."""
        csv_content = "account,ticker,quantity,avg_price\ntoss,MSFT,3,400.0\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 200
        assert r.json()["imported"] == 1

    def test_import_missing_required_column(self, client):
        """필수 컬럼 누락 → 400."""
        csv_content = "account,ticker,quantity\ntoss,AAPL,10\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 400
        assert "avg_price" in r.json()["detail"]

    def test_import_not_csv(self, client):
        """CSV가 아닌 파일 → 400."""
        r = client.post("/api/portfolio/import",
                        files={"file": ("data.txt", b"hello", "text/plain")})
        assert r.status_code == 400
        assert "CSV" in r.json()["detail"]

    def test_import_empty_header(self, client):
        """빈 CSV → 400."""
        r = client.post("/api/portfolio/import", files=_csv_file(""))
        assert r.status_code == 400

    def test_import_invalid_ticker(self, client):
        """유효하지 않은 ticker → errors에 포함."""
        csv_content = "account,ticker,quantity,avg_price\ntoss,invalid!,10,100.0\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 400
        assert "ticker" in r.json()["detail"]

    def test_import_invalid_account(self, client):
        """유효하지 않은 계좌 → errors에 포함."""
        csv_content = "account,ticker,quantity,avg_price\nfake,AAPL,10,100.0\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 400

    def test_import_invalid_number(self, client):
        """숫자 변환 실패 → errors에 포함."""
        csv_content = "account,ticker,quantity,avg_price\ntoss,AAPL,abc,100.0\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 400

    def test_import_zero_quantity(self, client):
        """quantity 0 → errors에 포함."""
        csv_content = "account,ticker,quantity,avg_price\ntoss,AAPL,0,100.0\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 400

    def test_import_partial_errors(self, client):
        """일부 행만 유효 → 유효한 행만 import, errors 반환."""
        csv_content = "account,ticker,quantity,avg_price\ntoss,AAPL,10,180.0\nfake,BAD!,0,0\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 200
        data = r.json()
        assert data["imported"] == 1
        assert len(data["errors"]) > 0

    def test_import_empty_field(self, client):
        """필수 필드가 비어있는 행 → errors."""
        csv_content = "account,ticker,quantity,avg_price\ntoss,,10,100.0\n"
        r = client.post("/api/portfolio/import", files=_csv_file(csv_content))
        assert r.status_code == 400

    def test_import_non_utf8(self, client):
        """비UTF-8 파일 → 400."""
        bad_bytes = b"\xc7\xd1\xb1\xdb"
        r = client.post("/api/portfolio/import",
                        files={"file": ("test.csv", bad_bytes, "text/csv")})
        assert r.status_code == 400
        assert "UTF-8" in r.json()["detail"]

    def test_import_over_max_rows(self, client):
        """500행 초과 → 400."""
        header = "account,ticker,quantity,avg_price\n"
        rows = "".join(f"toss,T{i:04d},1,100.0\n" for i in range(501))
        r = client.post("/api/portfolio/import", files=_csv_file(header + rows))
        assert r.status_code == 400
        assert "500" in r.json()["detail"]


class TestExport:
    """GET /api/portfolio/export tests."""

    def test_export_csv_empty(self, client):
        """빈 포트폴리오 CSV export."""
        r = client.get("/api/portfolio/export?format=csv")
        assert r.status_code == 200
        assert r.headers["content-type"] == "text/csv; charset=utf-8"
        content = r.text
        assert "account" in content

    def test_export_csv_with_data(self, seeded_client):
        """데이터 있는 CSV export."""
        r = seeded_client.get("/api/portfolio/export?format=csv")
        assert r.status_code == 200
        lines = r.text.strip().split("\n")
        assert len(lines) == 2
        assert "AAPL" in lines[1]

    def test_export_yaml_with_data(self, seeded_client):
        """데이터 있는 YAML export."""
        r = seeded_client.get("/api/portfolio/export?format=yaml")
        assert r.status_code == 200
        assert "yaml" in r.headers["content-type"]
        data = yaml.safe_load(r.text)
        assert "accounts" in data
        assert "toss" in data["accounts"]
        holdings = data["accounts"]["toss"]["holdings"]
        assert len(holdings) == 1
        assert holdings[0]["ticker"] == "AAPL"

    def test_export_invalid_format(self, client):
        """지원하지 않는 format → 400."""
        r = client.get("/api/portfolio/export?format=json")
        assert r.status_code == 400

    def test_export_default_csv(self, client):
        """format 미지정 → CSV 기본값."""
        r = client.get("/api/portfolio/export")
        assert r.status_code == 200
        assert r.headers["content-type"] == "text/csv; charset=utf-8"


class TestSamplePortfolio:
    """POST /api/portfolio/sample tests."""

    def test_load_sample(self, client):
        """샘플 포트폴리오 로드."""
        r = client.post("/api/portfolio/sample")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["loaded"] == 5

        r2 = client.get("/api/portfolio")
        assert r2.json()["count"] == 5

    def test_load_sample_replaces_existing(self, client):
        """샘플 재로드 시 기존 sample 계좌 교체."""
        client.post("/api/portfolio/sample")
        client.post("/api/portfolio/sample")
        r = client.get("/api/portfolio")
        assert r.json()["count"] == 5


class TestMetadata:
    """metadata JSON column roundtrip tests."""

    def test_post_with_metadata(self, client):
        """POST 시 metadata 저장."""
        r = client.post("/api/portfolio", json={
            "account": "test", "ticker": "TSLL",
            "quantity": 96, "avg_price": 16.93,
            "sector": "Leveraged_ETF",
            "metadata": {"flag": "SELL", "note": "레버리지 ETF 금지"},
        })
        assert r.status_code == 200

    def test_put_with_metadata(self, client):
        """PUT으로 metadata 수정."""
        client.post("/api/portfolio", json={
            "account": "test", "ticker": "AAPL",
            "quantity": 10, "avg_price": 190.0,
        })
        r = client.put("/api/portfolio/test/AAPL", json={
            "metadata": {"flag": "HOLD", "target": 220},
        })
        assert r.status_code == 200

    def test_metadata_roundtrip_yaml(self, client, tmp_path):
        """POST → YAML 동기화 → metadata 필드 복원 확인."""
        client.post("/api/portfolio", json={
            "account": "test", "ticker": "TSLL",
            "quantity": 96, "avg_price": 16.93,
            "sector": "Leveraged_ETF",
            "metadata": {"flag": "SELL"},
        })
        yaml_path = tmp_path / "portfolio.yaml"
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        holdings = data["accounts"]["test"]["holdings"]
        tsll = [h for h in holdings if h["ticker"] == "TSLL"][0]
        assert tsll["flag"] == "SELL"

    def test_metadata_in_import(self, tmp_path, monkeypatch):
        """import_portfolio.py가 YAML의 추가 필드를 metadata로 보존."""
        from nuri.core.db import query

        meta_db = tmp_path / "test.db"
        init_db(meta_db)

        yaml_path = tmp_path / "portfolio.yaml"
        yaml_content = {
            "accounts": {
                "test": {
                    "currency": "USD",
                    "holdings": [
                        {"ticker": "TSLL", "qty": 96, "avg": 16.93,
                         "sector": "Leveraged_ETF", "flag": "SELL"},
                    ],
                },
            },
        }
        with open(yaml_path, "w") as f:
            yaml.dump(yaml_content, f)

        import scripts.import_portfolio as imp
        records = imp.load_holdings(config_path=yaml_path)
        upsert_portfolio(records, db_path=meta_db)

        rows = query("SELECT metadata FROM portfolio WHERE ticker='TSLL'", db_path=meta_db)
        assert rows
        meta = json.loads(rows[0]["metadata"])
        assert meta["flag"] == "SELL"

    def test_metadata_invalid_json_ignored(self, tmp_path, monkeypatch):
        """DB에 잘못된 JSON이 있어도 에러 없이 무시."""
        from nuri.core.portfolio_sync import sync_portfolio_to_yaml

        bad_db = tmp_path / "test.db"
        init_db(bad_db)
        upsert_portfolio([{
            "account": "test", "ticker": "BAD",
            "quantity": 1, "avg_price": 100.0,
            "currency": "USD", "sector": "",
            "metadata": "not-valid-json{",
        }], db_path=bad_db)

        yaml_path = tmp_path / "out.yaml"
        count = sync_portfolio_to_yaml(config_path=yaml_path, db_path=bad_db)
        assert count == 1
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        bad = data["accounts"]["test"]["holdings"][0]
        assert bad["ticker"] == "BAD"
        assert "flag" not in bad

    def test_metadata_full_roundtrip(self, tmp_path, monkeypatch):
        """YAML → import → DB → sync → YAML: flag 완전 보존."""
        from nuri.core.portfolio_sync import sync_portfolio_to_yaml

        rt_db = tmp_path / "test.db"
        init_db(rt_db)

        yaml_path = tmp_path / "portfolio.yaml"
        yaml_content = {
            "accounts": {
                "kakaopay": {
                    "name": "카카오페이",
                    "currency": "USD",
                    "holdings": [
                        {"ticker": "TSLL", "qty": 96, "avg": 16.93,
                         "sector": "Leveraged_ETF", "flag": "SELL"},
                        {"ticker": "NVDA", "qty": 20, "avg": 132.14,
                         "sector": "Semiconductor"},
                    ],
                },
            },
        }
        with open(yaml_path, "w") as f:
            yaml.dump(yaml_content, f, allow_unicode=True)

        import scripts.import_portfolio as imp
        records = imp.load_holdings(config_path=yaml_path)
        upsert_portfolio(records, db_path=rt_db)

        sync_portfolio_to_yaml(config_path=yaml_path, db_path=rt_db)

        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        holdings = data["accounts"]["kakaopay"]["holdings"]
        tsll = [h for h in holdings if h["ticker"] == "TSLL"][0]
        nvda = [h for h in holdings if h["ticker"] == "NVDA"][0]
        assert tsll["flag"] == "SELL"
        assert "flag" not in nvda
        assert data["accounts"]["kakaopay"]["name"] == "카카오페이"
