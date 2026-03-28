"""
Nuri-Quant FastAPI — Phase A~E 분석 결과를 JSON API로 제공.

사용법:
    python -m nuri.api.main
    uvicorn nuri.api.main:app --reload --port 8000

보안:
    API_AUTH_ENABLED=true → JWT/API 키 인증 활성화
    API_KEY=xxx → 간단한 API 키 인증
    API_SECRET_KEY=xxx → JWT 서명 키
"""
import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from nuri.api.routes import (
    agents,
    dashboard,
    engine,
    evidence,
    external,
    portfolio,
    rebalance,
    regime,
    signals,
    stream,
    swing,
    targets,
    ticker,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
# yfinance 404/401 에러 로그 억제 (ETF/KS 종목에서 대량 발생)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# ─── Rate Limiter ───
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Nuri-Quant API",
    description="Open-source quant investment platform API",
    version="2.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ─── CORS 강화 ───
# 프로덕션: CORS_ORIGINS 환경변수로 허용 도메인 지정
_cors_origins_str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
_cors_origins = [o.strip() for o in _cors_origins_str.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)

# ─── 보안 헤더 미들웨어 ───
@app.middleware("http")
async def security_headers(request: Request, call_next):
    """보안 응답 헤더 추가."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ─── 라우터 등록 ───
app.include_router(portfolio.router, prefix="/api")
app.include_router(regime.router, prefix="/api")
app.include_router(signals.router, prefix="/api")
app.include_router(rebalance.router, prefix="/api")
app.include_router(engine.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(swing.router, prefix="/api")
app.include_router(ticker.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(stream.router, prefix="/api")
app.include_router(evidence.router, prefix="/api")
app.include_router(external.router, prefix="/api")
app.include_router(targets.router, prefix="/api")


# ─── 인증 엔드포인트 ───
@app.post("/api/auth/token")
@limiter.limit("5/15minutes")
async def login(request: Request):
    """JWT 토큰 발급. Body: {"password": "xxx"}."""
    from nuri.api.auth import create_token, verify_password

    dashboard_pw = os.getenv("DASHBOARD_PASSWORD", "")
    if not dashboard_pw:
        return JSONResponse({"error": "DASHBOARD_PASSWORD 미설정"}, status_code=503)

    body = await request.json()
    password = body.get("password", "")

    # 평문 비교 (기존 호환) 또는 bcrypt 비교
    if password == dashboard_pw or (dashboard_pw.startswith("$2") and verify_password(password, dashboard_pw)):
        token = create_token(subject="dashboard")
        return {"access_token": token, "token_type": "bearer"}

    return JSONResponse({"error": "인증 실패"}, status_code=401)


@app.get("/")
def root():
    """API root → redirect to docs."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/docs")


@app.get("/api/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import os

    import uvicorn
    port = int(os.getenv("API_PORT", "8001"))
    uvicorn.run("nuri.api.main:app", host="0.0.0.0", port=port, reload=True)
