"""Toss 증권 Open API 커넥터 — credential 세팅 + 인증 검증 (read-only).

목적(현 단계): `.env` 의 TOSS_API_KEY/TOSS_SECRET_KEY 가 올바른지 검증.
  `python -m nuri.collectors.toss --verify` → OAuth 토큰 발급 + 환율 smoke test.

OAuth 2.0 Client Credentials (POST /oauth2/token, x-www-form-urlencoded):
  body: grant_type=client_credentials&client_id={KEY}&client_secret={SECRET}
  resp: {access_token, token_type: "Bearer", expires_in: 86400}
토큰은 config/toss/cache/token.json 에 캐시 (client 당 1개·24h). 만료 마진 5분.

⚠️ STRATEGY §7.1 — 주문(create/modify/cancel) endpoint 는 **절대 호출 안 함**.
   시세/환율/잔고 read-only 만. 자동 매매 영구 deferred.

자격 증명 우선순위: 1) env (TOSS_API_KEY/TOSS_SECRET_KEY) 2) config/toss/toss_devlp.yaml
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from nuri.core.timezone import kst_now

load_dotenv()

logger = logging.getLogger(__name__)

TOSS_BASE = "https://openapi.tossinvest.com"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TOSS_DIR = _PROJECT_ROOT / "config" / "toss"
_TOKEN_CACHE = _TOSS_DIR / "cache" / "token.json"
_EXPIRY_MARGIN_SEC = 300  # 만료 5분 전 갱신


class TossCredentialsError(RuntimeError):
    """TOSS_API_KEY / TOSS_SECRET_KEY 미설정 또는 인증 실패."""


def _load_creds() -> tuple[str, str]:
    """(api_key, secret) — env 우선, config/toss/toss_devlp.yaml fallback.

    미설정 시 TossCredentialsError. secret 은 로깅 금지.
    """
    import os

    key = (os.getenv("TOSS_API_KEY") or "").strip()
    secret = (os.getenv("TOSS_SECRET_KEY") or "").strip()
    if key and secret:
        return key, secret

    yaml_path = _TOSS_DIR / "toss_devlp.yaml"
    if yaml_path.exists():
        import yaml

        cfg = yaml.safe_load(yaml_path.read_text()) or {}
        key = key or str(cfg.get("api_key", "")).strip()
        secret = secret or str(cfg.get("secret_key", "")).strip()
    if not (key and secret):
        raise TossCredentialsError(
            "TOSS_API_KEY / TOSS_SECRET_KEY 미설정 — .env 에 추가 후 재시도 "
            "(또는 config/toss/toss_devlp.yaml). 발급: https://developers.tossinvest.com"
        )
    return key, secret


def _read_cached_token() -> Optional[str]:
    """캐시된 access_token — 만료(마진 포함) 전이면 반환, 아니면 None."""
    if not _TOKEN_CACHE.exists():
        return None
    try:
        data = json.loads(_TOKEN_CACHE.read_text())
        expires_at = float(data.get("expires_at", 0))
        if expires_at - _EXPIRY_MARGIN_SEC > kst_now().timestamp():
            return str(data.get("access_token") or "") or None
    except Exception:  # noqa: BLE001 — 캐시 손상 시 무시하고 재발급
        return None
    return None


def _cache_token(access_token: str, expires_in: int) -> None:
    _TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_CACHE.write_text(
        json.dumps({"access_token": access_token, "expires_at": kst_now().timestamp() + int(expires_in)})
    )


def get_access_token(*, force: bool = False) -> str:
    """OAuth Client Credentials 토큰 — 캐시 재사용, 없으면 발급."""
    if not force:
        cached = _read_cached_token()
        if cached:
            return cached

    import requests

    key, secret = _load_creds()
    resp = requests.post(
        f"{TOSS_BASE}/oauth2/token",
        data={"grant_type": "client_credentials", "client_id": key, "client_secret": secret},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if resp.status_code != 200:
        raise TossCredentialsError(f"토큰 발급 실패 (HTTP {resp.status_code}): {resp.text[:200]}")
    body = resp.json()
    token = body.get("access_token")
    if not token:
        raise TossCredentialsError(f"응답에 access_token 없음: {body}")
    _cache_token(token, body.get("expires_in", 86400))
    return token


def _authed_get(path: str, params: dict[str, Any], *, account_seq: Optional[str] = None) -> dict[str, Any]:
    """Bearer 인증 GET — 계좌 endpoint 는 account_seq(X-Tossinvest-Account) 필요."""
    import requests

    headers = {"Authorization": f"Bearer {get_access_token()}"}
    if account_seq:
        headers["X-Tossinvest-Account"] = account_seq
    resp = requests.get(f"{TOSS_BASE}{path}", params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_exchange_rate(base: str = "USD", quote: str = "KRW") -> dict[str, Any]:
    """GET /api/v1/exchange-rate — USD/KRW 등 (read-only, 계좌 불필요).

    Returns: {rate, midRate, validFrom, validUntil, ...} (result 언랩).
    """
    data = _authed_get("/api/v1/exchange-rate", {"baseCurrency": base, "quoteCurrency": quote})
    return data.get("result", data)


def verify() -> int:
    """credential 검증 — 토큰 발급 + 환율 smoke test. secret/token 미출력.

    exit code: 0 = OK, 2 = creds/auth 실패.
    """
    try:
        token = get_access_token(force=True)
        print(f"✓ OAuth 토큰 발급 성공 (len={len(token)}, 캐시: {_TOKEN_CACHE})")
    except TossCredentialsError as e:
        print(f"✗ 인증 실패: {e}")
        return 2
    except Exception as e:  # noqa: BLE001 — 네트워크 등
        print(f"✗ 토큰 발급 중 오류: {e}")
        return 2

    try:
        fx = get_exchange_rate("USD", "KRW")
        print(f"✓ 환율 smoke test: USD/KRW = {fx.get('rate')} (valid {fx.get('validFrom')})")
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 토큰은 OK 였으나 환율 조회 실패: {e}")
        return 2
    print("✅ Toss Open API 적용 가능 — 키/시크릿 정상 동작 확인.")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="toss", description="Toss Open API connector (read-only)")
    parser.add_argument("--verify", action="store_true", help="키/시크릿 검증 (토큰+환율 smoke test)")
    args = parser.parse_args(argv)

    if args.verify:
        return verify()
    parser.print_help()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
