"""
API 인증 모듈 — JWT 토큰 + API 키 인증.

환경변수:
    API_SECRET_KEY: JWT 서명 키 (미설정 시 랜덤 생성, 재시작마다 변경)
    API_KEY: 간단한 API 키 인증 (Authorization: Bearer <key>)
    API_AUTH_ENABLED: "true"이면 인증 활성화 (기본: "false", 개발 편의)

사용법:
    from nuri.api.auth import require_auth, require_write_auth

    @router.get("/data")
    def get_data(user=Depends(require_auth)):
        ...

    @router.post("/data")
    def write_data(user=Depends(require_write_auth)):
        ...
"""

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

# ─── 설정 ───
_SECRET_KEY = os.getenv("API_SECRET_KEY", secrets.token_hex(32))
_API_KEY = os.getenv("API_KEY", "")
_AUTH_ENABLED = os.getenv("API_AUTH_ENABLED", "false").lower() == "true"
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRE_HOURS = 24

_security = HTTPBearer(auto_error=False)


# ─── 비밀번호 해싱 (bcrypt + constant-time compare) ───
def hash_password(password: str) -> str:
    """bcrypt 해싱."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """bcrypt constant-time 비교."""
    return bcrypt.checkpw(password.encode(), hashed.encode())


# ─── JWT 토큰 ───
def create_token(subject: str, expires_hours: int = _JWT_EXPIRE_HOURS) -> str:
    """JWT 토큰 생성."""
    payload = {
        "sub": subject,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=expires_hours),
    }
    return jwt.encode(payload, _SECRET_KEY, algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """JWT 토큰 디코딩. 실패 시 None."""
    try:
        return jwt.decode(token, _SECRET_KEY, algorithms=[_JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.debug("JWT 만료")
        return None
    except jwt.InvalidTokenError:
        logger.debug("JWT 무효")
        return None


# ─── 인증 의존성 ───
async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> dict:
    """읽기 엔드포인트 인증. AUTH_ENABLED=false면 통과."""
    if not _AUTH_ENABLED:
        return {"sub": "anonymous", "auth": "disabled"}

    if credentials is None:  # pragma: no cover — FastAPI dependency injects credentials in tests
        raise HTTPException(status_code=401, detail="인증 필요")

    token = credentials.credentials

    # API 키 확인
    if _API_KEY and _constant_time_compare(token, _API_KEY):
        return {"sub": "api_key", "auth": "api_key"}

    # JWT 확인
    payload = decode_token(token)
    if payload:
        return payload

    raise HTTPException(status_code=401, detail="유효하지 않은 토큰")


async def require_write_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> dict:
    """쓰기 엔드포인트 인증 (POST/DELETE). AUTH_ENABLED=false면 통과."""
    return await require_auth(request, credentials)


def _constant_time_compare(a: str, b: str) -> bool:
    """타이밍 공격 방지 비교 (constant-time string comparison).

    Uses secrets.compare_digest from the standard library — the canonical
    Python primitive for constant-time equality. The earlier implementation
    hashed both sides with SHA-256 first, which CodeQL flagged as
    "weak password hashing" (false positive: hashing wasn't the goal,
    constant-time comparison was). compare_digest is shorter and correct.
    """
    return secrets.compare_digest(a.encode(), b.encode())
