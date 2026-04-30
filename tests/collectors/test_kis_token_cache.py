"""KIS access token 캐시 동작 회귀 테스트 (Issue #532).

회귀 보호 대상:
    - Cache 위치 결정성: `.env` only 자격 증명 환경에서도 cache 가 항상
      project-local `config/kis/cache/` 에 쓰여야 한다 (legacy `~/KIS/cache/` 로
      흘러가면 2-machine setup 에서 sync 불가 → 매일 새 토큰 발급 노이즈).
    - TTL 적중: TTL 이내 두 번째 호출은 HTTP 요청 없이 캐시된 토큰을 반환.
    - JSON 손상 시 재발급: 캐시 파일이 깨졌으면 silently 무시 + 새로 발급.

Issue: https://github.com/researcherhojin/nuri-quant/issues/532
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from nuri.collectors.kis_realtime import (
    KISCredentials,
    _resolve_token_cache_dir,
    get_access_token,
)


@pytest.fixture
def fake_creds() -> KISCredentials:
    """테스트용 가짜 자격 증명 (실제 KIS 호출 X)."""
    return KISCredentials(
        app_key="fake_key",
        app_secret="fake_secret",
        account="00000000",
        hts_id="fake_hts",
        mode="prod",
    )


@pytest.fixture
def project_cache_dir(tmp_path):
    """project-local cache 위치 (config/kis/cache 시뮬레이션)."""
    d = tmp_path / "project" / "config" / "kis" / "cache"
    return d


@pytest.fixture
def legacy_cache_dir(tmp_path):
    """레거시 ~/KIS/cache 위치."""
    d = tmp_path / "home" / "KIS" / "cache"
    return d


# ═══════════════════════════════════════════════════════
# Cache 위치 결정성 (Issue #532 핵심 회귀)
# ═══════════════════════════════════════════════════════


class TestCacheLocationDeterminism:
    """Cache 는 항상 project-local 이어야 한다 (yaml 존재 여부 무관)."""

    def test_cache_dir_is_project_local_when_yaml_absent(
        self, project_cache_dir, legacy_cache_dir
    ):
        """`.env` only 셋업 (yaml 없음) → cache 가 project-local 로 결정됨.

        이 테스트가 실패하면 Issue #532 재발: cache 가 legacy `~/KIS/cache/` 로
        흘러가서 2-machine sync 안 되고 매일 새 토큰 발급됨.
        """
        # yaml 부재 (modern .env-only setup)
        project_kis_dir = project_cache_dir.parent  # config/kis/
        project_kis_dir.mkdir(parents=True, exist_ok=True)
        # NOTE: kis_devlp.yaml 을 일부러 만들지 않음 (.env only 시나리오)

        resolved = _resolve_token_cache_dir(project_kis_dir, legacy_cache_dir.parent)
        assert resolved == project_cache_dir, (
            f"`.env` only 셋업에서 cache 가 legacy 로 흘러감: {resolved} "
            f"(expected: {project_cache_dir}). Issue #532 회귀."
        )

    def test_cache_dir_is_project_local_when_yaml_present(
        self, project_cache_dir, legacy_cache_dir
    ):
        """yaml 있을 때도 동일하게 project-local cache. 결정성 보장."""
        project_kis_dir = project_cache_dir.parent
        project_kis_dir.mkdir(parents=True, exist_ok=True)
        (project_kis_dir / "kis_devlp.yaml").write_text("placeholder: true")

        resolved = _resolve_token_cache_dir(project_kis_dir, legacy_cache_dir.parent)
        assert resolved == project_cache_dir


# ═══════════════════════════════════════════════════════
# TTL 적중 — 같은 token 반환 + HTTP 1회만
# ═══════════════════════════════════════════════════════


class TestTokenCacheTTL:
    """TTL 이내 두 번째 호출은 캐시된 token 반환 (HTTP 0회)."""

    def test_two_calls_within_ttl_only_one_http_request(
        self, fake_creds, project_cache_dir
    ):
        """24h cache 의 핵심: 2번 호출 → HTTP 1번만 발생."""
        project_cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = project_cache_dir / "token_prod.json"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "TOKEN_FROM_HTTP",
            "expires_in": 86400,
        }

        with (
            patch(
                "nuri.collectors.kis_realtime.TOKEN_CACHE_DIR", project_cache_dir
            ),
            patch("nuri.collectors.kis_realtime.requests.post", return_value=mock_response) as mock_post,
        ):
            # 1차: HTTP 호출 → cache 작성
            tok1 = get_access_token(fake_creds)
            # 2차: cache hit → HTTP 없음
            tok2 = get_access_token(fake_creds)

        assert tok1 == "TOKEN_FROM_HTTP"
        assert tok2 == "TOKEN_FROM_HTTP", "Cache hit 시 같은 token 반환해야 함"
        assert mock_post.call_count == 1, (
            f"TTL 이내 2회 호출이 HTTP {mock_post.call_count}회 발생 — "
            "Issue #532 회귀 (cache 미작동)"
        )
        assert cache_file.exists(), "Cache 파일이 작성되어야 함"

    def test_expired_cache_triggers_new_issue(self, fake_creds, project_cache_dir):
        """TTL 초과된 cache 는 무시 + 새로 발급."""
        project_cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = project_cache_dir / "token_prod.json"
        # 25시간 전 issued (TTL 23h 초과)
        cache_file.write_text(
            json.dumps({
                "access_token": "STALE_TOKEN",
                "issued_at": time.time() - 25 * 3600,
                "expires_in": 86400,
            })
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "FRESH_TOKEN",
            "expires_in": 86400,
        }

        with (
            patch(
                "nuri.collectors.kis_realtime.TOKEN_CACHE_DIR", project_cache_dir
            ),
            patch("nuri.collectors.kis_realtime.requests.post", return_value=mock_response) as mock_post,
        ):
            tok = get_access_token(fake_creds)

        assert tok == "FRESH_TOKEN"
        assert mock_post.call_count == 1

    def test_corrupted_cache_falls_back_to_new_issue(
        self, fake_creds, project_cache_dir
    ):
        """깨진 JSON cache → silently 무시 + 새로 발급."""
        project_cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = project_cache_dir / "token_prod.json"
        cache_file.write_text("{ corrupted json !!!")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "RECOVERY_TOKEN",
            "expires_in": 86400,
        }

        with (
            patch(
                "nuri.collectors.kis_realtime.TOKEN_CACHE_DIR", project_cache_dir
            ),
            patch("nuri.collectors.kis_realtime.requests.post", return_value=mock_response),
        ):
            tok = get_access_token(fake_creds)

        assert tok == "RECOVERY_TOKEN"


# ═══════════════════════════════════════════════════════
# Mode 분리 — prod / paper 별 cache 파일
# ═══════════════════════════════════════════════════════


class TestModeSeparation:
    """prod 와 paper token 은 다른 파일로 cache."""

    def test_prod_and_paper_use_separate_cache_files(self, project_cache_dir):
        """prod cache 가 paper 호출에 새지 않도록."""
        project_cache_dir.mkdir(parents=True, exist_ok=True)
        prod_creds = KISCredentials("k", "s", "1", "h", "prod")
        paper_creds = KISCredentials("k", "s", "1", "h", "paper")

        responses = [
            MagicMock(status_code=200, **{"json.return_value": {"access_token": "PROD_TOK", "expires_in": 86400}}),
            MagicMock(status_code=200, **{"json.return_value": {"access_token": "PAPER_TOK", "expires_in": 86400}}),
        ]

        with (
            patch(
                "nuri.collectors.kis_realtime.TOKEN_CACHE_DIR", project_cache_dir
            ),
            patch("nuri.collectors.kis_realtime.requests.post", side_effect=responses),
        ):
            assert get_access_token(prod_creds) == "PROD_TOK"
            assert get_access_token(paper_creds) == "PAPER_TOK"

        assert (project_cache_dir / "token_prod.json").exists()
        assert (project_cache_dir / "token_paper.json").exists()
