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

from dotenv import load_dotenv

load_dotenv()  # .env → os.environ (CORS_ORIGINS 등)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from nuri.api.routes import (
    actions,
    agents,
    alpha,
    coverage,
    dashboard,
    decisions,
    engine,
    evidence,
    external,
    learning_memory,
    pipeline,
    portfolio,
    rebalance,
    regime,
    signals,
    stream,
    swing,
    targets,
    ticker,
    trades,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nuri.api")
# yfinance 404/401 에러 로그 억제 (ETF/KS 종목에서 대량 발생)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# ─── 보안 경고 ───
if not os.getenv("API_SECRET_KEY"):
    logger.warning("API_SECRET_KEY 미설정 — 재시작 시 JWT 무효화됩니다. .env에 설정하세요.")

# ─── Rate Limiter ───
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"],  # 전역 기본: 읽기 60/min
)

app = FastAPI(
    title="Nuri-Quant API",
    description="Open-source quant investment platform API",
    version="0.1.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

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
    """보안 응답 헤더 추가.

    X-Frame-Options: SAMEORIGIN — /evidence 페이지 (Next.js :3000) 가 Plotly
    HTML evidence 를 `/api/evidence/{chart_id}` iframe 으로 embed. Next.js proxy
    가 same-origin 으로 serve 하므로 SAMEORIGIN 정책이 허용. DENY 로 두면 chart
    iframe 이 blocked (2026-04-20 Playwright audit 에서 5 violations 검출).
    Cross-origin clickjacking 은 여전히 차단 — frontend/next.config.ts CSP
    `frame-ancestors 'self'` 와 일관.
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ─── 라우터 등록 ───
app.include_router(actions.router, prefix="/api")
app.include_router(portfolio.router, prefix="/api")
app.include_router(regime.router, prefix="/api")
app.include_router(signals.router, prefix="/api")
app.include_router(rebalance.router, prefix="/api")
app.include_router(coverage.router, prefix="/api")
app.include_router(engine.router, prefix="/api")
app.include_router(pipeline.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(swing.router, prefix="/api")
app.include_router(ticker.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(stream.router, prefix="/api")
app.include_router(evidence.router, prefix="/api")
app.include_router(external.router, prefix="/api")
app.include_router(targets.router, prefix="/api")
app.include_router(trades.router, prefix="/api")
app.include_router(decisions.router, prefix="/api")
app.include_router(alpha.router, prefix="/api")
app.include_router(learning_memory.router, prefix="/api")


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
