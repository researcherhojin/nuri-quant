# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

IRIS (Investment Research & Intelligence System) — 개인 퀀트 투자 분석 플랫폼.
총 자산 ~2.27억원, 5개 계좌 (카카오페이/미래에셋/토스/연금저축/IRP), 27종목.
Python 3.11+, SQLite, MCP 연동.

3-phase evolution:
- **Phase 1** (Foundation): Data collection + Claude Code analysis + Discord alerts
- **Phase 2** (LLM Benchmark): Local LLM model comparison on M3 Max via Ollama
- **Phase 3** (Quant Pipeline): Multi-factor models, backtesting, risk management

2-machine setup: M3 Max MacBook (dev) ↔ M2 Pro Mac Mini (24/7 production via cron).

## Commands

```bash
# Initial setup
make setup          # runs setup.sh + DB migration + portfolio import

# Data collection
make collect        # all collectors (stock, macro, technical, fear_greed, ark)
python -m iris.collectors.stock              # single collector
python -m iris.collectors.stock --market kr  # Korean market only

# Analysis
make analyze        # portfolio + sector + risk analysis
python -m iris.analysis.portfolio            # single analysis module

# Reporting & alerts
make report         # daily report generation

# Testing
make test           # pytest tests/ -v
python -m pytest tests/test_collectors.py -v # single test file

# Phase 2
make benchmark      # LLM benchmark (all models)

# Phase 3
make backtest       # run backtest engine

# Deployment
make deploy         # deploy to Mac Mini
make backup         # DB backup (30-day rolling)
```

## Architecture

3-layer architecture with data flowing: **Collectors → Analysis → Alerts**

- **Layer 1 — Collectors** (`iris/collectors/`): All inherit `BaseCollector` (in `base.py`). Each collector gathers one data type: stock prices (yfinance), macro indicators (FRED API), technical signals (TA-Lib), Fear&Greed (CNN scraping), ARK trades, events calendar, news.
- **Layer 2 — Analysis** (`iris/analysis/`): Portfolio summary, performance attribution, correlation matrix, sector/geographic exposure, risk metrics (VaR, Sharpe, max drawdown), rebalancing suggestions.
- **Layer 3 — Alerts** (`iris/alerts/`): Discord bot for 24/7 notifications — daily reports, price swing alerts (±3%), ARK trade alerts, FOMC/earnings D-1 reminders, monthly rebalance alerts.
- **Phase 2 — LLM** (`iris/llm/`): Ollama-based local LLM benchmarking and investment analysis pipeline.
- **Phase 3 — Quant** (`iris/quant/`): Factor models (momentum/value/quality/sentiment), Backtrader backtesting, signal generation, risk management (position sizing, stop-loss, portfolio optimization).

All DB access goes through `iris/db.py` only. Database is SQLite at `data/portfolio.db`.

## MCP Integration

Claude Code accesses the SQLite DB directly via MCP (configured in `.mcp.json`). This enables natural language queries against portfolio data:

```bash
# MCP setup (already in .mcp.json)
claude mcp add iris-db -- npx -y @modelcontextprotocol/server-sqlite ./data/portfolio.db
```

Common query patterns:
- 포트폴리오 현황 → `SELECT * FROM portfolio`
- 종목 기술적 분석 → `signals` table (RSI, MACD, BB)
- 매크로/공포탐욕 → `macro` table (`indicator = 'fear_greed'`)
- ARK 매매 내역 → `ark` table
- 다음 주 이벤트 → `events` table

## DB Schema

| Table | Key columns |
|-------|-------------|
| `prices` | ticker, date, open, high, low, close, volume, adj_close |
| `portfolio` | account, ticker, quantity, avg_price, currency, sector |
| `macro` | indicator, date, value |
| `ark` | date, ticker, direction, shares, weight, fund |
| `signals` | ticker, date, rsi_14, macd, macd_signal, macd_hist, bb_upper/middle/lower, sma_20/50/200, ema_12/26 |
| `events` | date, event_type, ticker, description, importance |
| `factors` | [Phase 3] ticker, date, momentum/value/quality/composite_score |
| `backtests` | [Phase 3] strategy_id, start/end_date, total_return, sharpe, max_drawdown, win_rate |
| `llm_bench` | [Phase 2] model, prompt_type, response, score, latency_ms, timestamp |

## Code Conventions

- Python 3.11+ with type hints
- Korean comments (한국어 주석), English variable/function names
- All collectors inherit `BaseCollector`
- Configuration in YAML (`config/`), secrets in `.env` (git-ignored)
- DB never accessed directly — always through `iris.db` module
- Korean stock tickers use `.KS` suffix (e.g., `005930.KS` for 삼성전자, `000660.KS` for SK하이닉스)

## Key Dependencies & Data Sources

| Package | Purpose | Data Source |
|---------|---------|-------------|
| yfinance | Stock prices, fundamentals | Yahoo Finance |
| fredapi | Macro indicators (rates, CPI, oil) | FRED API (key required) |
| TA-Lib | Technical indicators (RSI, MACD, BB, MA) | Computed from prices |
| beautifulsoup4 | Fear & Greed Index | CNN scraping |
| discord.py | Alert notifications | Discord bot (token required) |
| backtrader | [Phase 3] Backtesting engine | — |

Requires `brew install ta-lib` before `pip install`. Fallback: if yfinance is blocked, Alpha Vantage free tier as backup.

## Production Schedule (Mac Mini Cron)

| Time (KST) | Task | Frequency |
|-------------|------|-----------|
| 09:00–15:30 | Korean market stock collection | Every 5 min, weekdays |
| 23:30–06:00 | US market stock collection | Every 5 min, weekdays |
| Every hour | Macro indicators | Hourly |
| 07:00 | Technical indicators + events calendar | Daily (post-market) |
| 07:30 | ARK trade tracking | Daily (post-market) |
| 08:00 | Fear & Greed + Daily Report | Daily |
| Every 6h | News collection | 4x daily |
| 00:00 | DB backup (30-day rolling) | Daily |

## Investment Rules (항상 참고)

1. 단일 종목 비중 15% 이하 유지
2. 레버리지 ETF(TSLL 등) 장기 보유 금지
3. 분할매수 필수 — 한 번에 몰빵 금지
4. 장 초반 30분(9:00~9:30 한국장, 23:30~00:00 미장) 매수 금지
5. 공포탐욕지수 20 이하 = 우량주 매도 금지, 현금 보존
6. 매매 결정 시 기술적 + 펀더멘털 + 매크로 3가지 모두 확인
7. 모든 시그널은 "판단 보조" — 최종 결정은 사람이 한다

## Risk Constraints

```yaml
max_single_position: 15%
max_sector_exposure: 35%
max_correlation: 0.80      # warning threshold
stop_loss: -20%            # per stock
portfolio_stop: -10%       # total portfolio
rebalance_threshold: ±5%   # drift trigger
leverage_ban: true
no_first_30min: true
```
