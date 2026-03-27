"""
Nuri-Quant FastAPI — Phase A~E 분석 결과를 JSON API로 제공.

사용법:
    python -m nuri.api.main
    uvicorn nuri.api.main:app --reload --port 8000
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nuri.api.routes import agents, dashboard, engine, portfolio, rebalance, regime, signals, stream, swing, ticker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
# yfinance 404/401 에러 로그 억제 (ETF/KS 종목에서 대량 발생)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

app = FastAPI(
    title="Nuri-Quant API",
    description="Open-source quant investment platform API",
    version="1.0.0",
)

# CORS (Next.js dev server에서 접근 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

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
