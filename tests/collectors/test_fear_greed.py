"""Per-collector tests for fear_greed.

Split from tests/test_collectors_all.py for module-level isolation.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestFearGreedCollector:
    def test_instantiate(self):
        from nuri.collectors.fear_greed import FearGreedCollector

        c = FearGreedCollector()
        assert c.name == "fear_greed"

    def test_save_records(self, db_path):
        from nuri.collectors.fear_greed import FearGreedCollector

        c = FearGreedCollector()
        records = [{"indicator": "fear_greed", "date": "2026-03-30", "value": 55.0, "source": "cnn_api"}]
        count = c.save(records)
        assert count == 1

    @patch("nuri.collectors.fear_greed.requests")
    def test_collect_api(self, mock_requests):
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"fear_and_greed": {"score": 62.5}}
        mock_requests.get.return_value = mock_resp
        c = FearGreedCollector()
        result = c._collect_api()
        assert len(result) == 1
        assert result[0]["value"] == 62.5


class TestFearGreedCollectorAPIAndScrape:
    def test_collect_api_success(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"fear_and_greed": {"score": 55.0}}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", MagicMock(return_value=mock_resp))
        results = FearGreedCollector().collect()
        assert len(results) == 1 and results[0]["value"] == 55.0

    def test_collect_api_value_key(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"fear_and_greed": {"value": 72.0}}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", MagicMock(return_value=mock_resp))
        assert FearGreedCollector().collect()[0]["value"] == 72.0

    def test_collect_api_no_data(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", MagicMock(return_value=mock_resp))
        assert FearGreedCollector().collect() == []

    def test_collect_api_fail_scrape_fallback(self, monkeypatch):
        from nuri.collectors.fear_greed import FearGreedCollector

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("API down")
            mock_resp = MagicMock()
            mock_resp.text = '<html><text class="market-fng-gauge__dial-number-value">45</text></html>'
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", mock_get)
        results = FearGreedCollector().collect()
        assert results[0]["value"] == 45.0

    def test_collect_both_fail(self, monkeypatch):
        """전면 실패는 `[]` 가 아니라 raise (#1042). 이전엔 `== []` 를 단언해 결함을 잠그고 있었다."""
        from nuri.collectors.fear_greed import FearGreedCollector

        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", MagicMock(side_effect=Exception("all down")))
        with pytest.raises(Exception, match="all down"):
            FearGreedCollector().collect()

    def test_scrape_no_score_found(self, monkeypatch):
        """API 가 죽은 뒤 폴백까지 빈손이면 실패다 — `[]` 가 아니라 raise (#1042).

        API 가 200 인데 내용이 빈 경우(`test_collect_api_no_data`)와 갈리는 지점이다.
        거긴 예외가 없으니 NO_DATA 고, 여긴 예외가 있었으니 수집 실패다.
        """
        from nuri.collectors.fear_greed import FearGreedCollector

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("API down")
            mock_resp = MagicMock()
            mock_resp.text = "<html><body>No score here</body></html>"
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", mock_get)
        with pytest.raises(Exception, match="API down"):
            FearGreedCollector().collect()

    def test_save(self, db_with_portfolio):
        from nuri.collectors.fear_greed import FearGreedCollector

        assert (
            FearGreedCollector().save(
                [{"indicator": "fear_greed", "date": "2025-01-30", "value": 55.0, "source": "CNN"}]
            )
            == 1
        )


class TestFearGreedFailedVsNoData:
    """전면 실패와 "오늘 값 없음"의 구분을 잠근다 (#1042 — coingecko #1043 과 같은 규약).

    구분이 사라지면 `collector_runs.status` 에 둘 다 `finished` 가 박히고 `#ops` 알림도
    안 뜬다. `fear_greed` 는 composite factor 의 sentiment 성분과 euphoria 감지
    (vix<12 AND fg>80) 로 들어가므로, 조용히 어두워지면 그 판단이 근거 없이 돌아간다.
    """

    def test_total_failure_raises_instead_of_returning_empty(self, monkeypatch):
        """raise 를 걷어내면 FAIL."""
        from nuri.collectors.fear_greed import FearGreedCollector

        monkeypatch.setattr(
            "nuri.collectors.fear_greed.requests.get",
            MagicMock(side_effect=RuntimeError("cnn down")),
        )
        with pytest.raises(RuntimeError, match="cnn down"):
            FearGreedCollector().collect()

    def test_empty_payload_is_not_a_failure(self, monkeypatch):
        """조건에서 `errors and` 를 빼면 FAIL (IndexError — errors 가 비어 있다).

        API 가 200 인데 `fear_and_greed` 키가 없으면 예외가 없다 — NO_DATA 이므로
        `[]` 가 그대로 나가야 하고, 폴백 스크래핑도 타면 안 된다. 이 두 성질
        (반환값 · 폴백 미실행)을 같이 단언해야 `errors and` 절이 실제로 잠긴다.
        """
        from nuri.collectors.fear_greed import FearGreedCollector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        get = MagicMock(return_value=mock_resp)
        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", get)

        assert FearGreedCollector().collect() == []
        assert get.call_count == 1, "API 가 성공(빈 응답)했는데 스크래핑 폴백까지 탔다"

    def test_first_error_is_raised_not_the_last(self, monkeypatch):
        """`errors[0]` → `errors[-1]` 로 바꾸면 FAIL.

        마지막은 항상 스크래핑이라, 그걸 올리면 진짜 원인(API 쪽 4xx/5xx)이 알림에서
        사라진다.
        """
        from nuri.collectors.fear_greed import FearGreedCollector

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("FIRST cnn api 503")
            raise RuntimeError("LAST scrape timeout")

        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", mock_get)
        with pytest.raises(RuntimeError, match="FIRST cnn api 503"):
            FearGreedCollector().collect()

    def test_scrape_fallback_still_rescues_a_dead_api(self, monkeypatch):
        """과잉 차단 방지 — API 가 죽어도 스크래핑이 점수를 찾으면 성공이어야 한다."""
        from nuri.collectors.fear_greed import FearGreedCollector

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("api down")
            mock_resp = MagicMock()
            mock_resp.text = '<text class="market-fng-gauge__dial-number-value">42.0</text>'
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        monkeypatch.setattr("nuri.collectors.fear_greed.requests.get", mock_get)
        records = FearGreedCollector().collect()
        assert len(records) == 1
        assert records[0]["value"] == 42.0
        assert records[0]["source"] == "CNN_scrape"
