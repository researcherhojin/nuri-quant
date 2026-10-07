# pyright: reportArgumentType=false
"""KIS (한국투자증권) Open API 실시간 시세 수집기.

(KISCredentials | None Pylance narrowing — caller 가 None check 후 호출, runtime 정상.)

자격 증명 우선순위:
    1. .env: KIS_PROD_APP_KEY/SECRET (실전), KIS_PAPER_APP_KEY/SECRET (모의)
    2. config/kis/kis_devlp.yaml (프로젝트 내 gitignored, KIS Open API SDK 호환)
    3. ~/KIS/config/kis_devlp.yaml (레거시 위치 fallback, 하위 호환)

기능:
    - --check-creds: 자격 증명 확인만 (호출 X)
    - 보유 종목의 현재가 inquire-price (한국+미국)
    - 24h token 캐시 (1분 cooldown 회피, config/kis/cache/)
    - DB upsert (prices 테이블)

사용법:
    python -m nuri.collectors.kis_realtime --check-creds
    python -m nuri.collectors.kis_realtime
    python -m nuri.collectors.kis_realtime --mode paper
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from dotenv import load_dotenv

from nuri.collectors.base import BaseCollector
from nuri.core.db import get_tickers, query, upsert_prices
from nuri.core.market_calendar import nyse_holidays
from nuri.core.timezone import kst_now, today_kst

load_dotenv()
logger = logging.getLogger(__name__)

# ── 상수 ──

PROD_BASE = "https://openapi.koreainvestment.com:9443"
PAPER_BASE = "https://openapivts.koreainvestment.com:29443"

TOKEN_CACHE_TTL_SEC = 23 * 3600  # 23h (실제 24h, 마진 1h)
TOKEN_COOLDOWN_SEC = 60  # KIS 1분 cooldown

# KIS 자격 증명 + token cache 위치 (우선순위 순):
#   1) config/kis/ — 프로젝트 내 gitignored, 권장
#   2) ~/KIS/ — 레거시 위치, 하위 호환 fallback
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_KIS_NEW_DIR = _PROJECT_ROOT / "config" / "kis"
_KIS_LEGACY_DIR = Path.home() / "KIS"


def _resolve_kis_paths(new_dir: Path, legacy_dir: Path) -> tuple[Path, Path]:
    """KIS yaml / cache 경로 결정. 새 위치 우선, 없으면 레거시 fallback.

    Args:
        new_dir: 프로젝트 내 KIS 디렉토리 (config/kis/)
        legacy_dir: 레거시 위치 (~/KIS/)

    Returns:
        (kis_yaml_path, token_cache_dir) 튜플
    """
    if (new_dir / "kis_devlp.yaml").exists():
        return new_dir / "kis_devlp.yaml", new_dir / "cache"
    # 레거시 또는 아예 없는 경우: legacy 위치 default (테스트 patch 호환)
    return legacy_dir / "config" / "kis_devlp.yaml", legacy_dir / "cache"


def _resolve_token_cache_dir(new_dir: Path, legacy_dir: Path) -> Path:
    """Token cache 경로 결정 (Issue #532).

    `_resolve_kis_paths` 와 다르게 **yaml 존재 여부와 무관하게 항상 project-local
    `config/kis/cache/` 사용**. 이유:

    1. **결정성**: `.env` only 셋업 (yaml 부재) 에서도 cache 위치가 예측 가능.
       기존 로직은 yaml 없으면 `~/KIS/cache/` 로 fallback → "cache 가 어디
       갔는지" 추적 어려움 → Issue #532 의 "매일 새 토큰 발급" 노이즈 원인.
    2. **2-machine setup 안전**: project-local 이면 양쪽 머신에서 동일 경로
       (각자 cache 보유, sync 는 안 되지만 위치는 동일).
    3. **gitignored 보장**: `.gitignore` 가 `config/kis/*` 전체 ignore →
       토큰 git 유출 위험 없음.

    Args:
        new_dir: 프로젝트 내 KIS 디렉토리 (config/kis/)
        legacy_dir: 레거시 위치 (~/KIS/) — 현재는 사용 안 함, 호환성 위해 유지

    Returns:
        token cache 디렉토리 Path
    """
    del legacy_dir  # 의도적으로 미사용 (legacy fallback 제거)
    return new_dir / "cache"


# Module load 시 1회 결정. 테스트는 KIS_YAML_PATH / TOKEN_CACHE_DIR 를 patch.
KIS_YAML_PATH, _ = _resolve_kis_paths(_KIS_NEW_DIR, _KIS_LEGACY_DIR)
TOKEN_CACHE_DIR = _resolve_token_cache_dir(_KIS_NEW_DIR, _KIS_LEGACY_DIR)

# KIS rate limit (KIS 공지 2026.03.20 + 실측):
#   - 실전(prod) 신규: 초당 3건 → 0.4s 간격 (초당 2.5건, 안전 마진)
#   - 실전(prod) 갱신/기존: 기본 유량 (정확값 미공시) — 0.4s로 안전
#   - 모의(paper): 더 낮은 제한 → 1.0s 간격 (초당 1건)
# EXCD 폴백 (NAS→NYS→AMS) 시도 사이에도 짧은 sleep 추가.
KIS_REQUEST_INTERVAL_PROD = 0.4
KIS_REQUEST_INTERVAL_PAPER = 1.0
KIS_EXCD_RETRY_INTERVAL_SEC = 0.4
KIS_RATE_LIMIT_RETRY_DELAY_SEC = 1.5  # rate limit 후 충분히 회복


@dataclass
class KISCredentials:
    """KIS 자격 증명 (prod/paper)."""

    app_key: str
    app_secret: str
    account: str
    hts_id: str
    mode: str  # "prod" | "paper"

    @property
    def base_url(self) -> str:
        return PROD_BASE if self.mode == "prod" else PAPER_BASE

    def is_valid(self) -> bool:
        return bool(self.app_key and self.app_secret)


# ═══════════════════════════════════════════════════════
# 자격 증명 로드
# ═══════════════════════════════════════════════════════


def load_credentials(mode: str = "prod") -> KISCredentials | None:
    """KIS 자격 증명 로드. 우선순위: .env → config/kis/kis_devlp.yaml → ~/KIS/config/kis_devlp.yaml.

    Args:
        mode: "prod" (실전) | "paper" (모의)
    """
    prefix = "KIS_PROD" if mode == "prod" else "KIS_PAPER"
    creds = KISCredentials(
        app_key=os.getenv(f"{prefix}_APP_KEY", ""),
        app_secret=os.getenv(f"{prefix}_APP_SECRET", ""),
        account=os.getenv(f"{prefix}_ACCOUNT", ""),
        hts_id=os.getenv("KIS_HTS_ID", ""),
        mode=mode,
    )
    if creds.is_valid():
        return creds

    # YAML fallback (KIS SDK 호환) — module-level KIS_YAML_PATH 사용 (테스트 patch 호환)
    if KIS_YAML_PATH.exists():
        try:
            import yaml

            with open(KIS_YAML_PATH, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            yaml_prefix = "my_app" if mode == "prod" else "paper_app"
            yaml_secret = "my_sec" if mode == "prod" else "paper_sec"
            yaml_account = "my_acct_stock" if mode == "prod" else "my_paper_stock"
            creds = KISCredentials(
                app_key=str(data.get(yaml_prefix, "")),
                app_secret=str(data.get(yaml_secret, "")),
                account=str(data.get(yaml_account, "")),
                hts_id=str(data.get("my_htsid", "")),
                mode=mode,
            )
            if creds.is_valid():
                # 경로 로깅 — 프로젝트 내부면 상대경로, 외부면 generic 표기 (사용자명 노출 방지)
                try:
                    rel_path = KIS_YAML_PATH.relative_to(_PROJECT_ROOT)
                    logger.info("KIS 자격 증명 로드: %s (%s)", rel_path, mode)
                except ValueError:
                    logger.info("KIS 자격 증명 로드: ~/KIS/config/kis_devlp.yaml (%s)", mode)
                return creds
        except Exception as e:
            logger.warning("KIS YAML 로드 실패: %s", e)

    return None


# ═══════════════════════════════════════════════════════
# Token 발급 + 캐시
# ═══════════════════════════════════════════════════════


def _token_cache_path(creds: KISCredentials) -> Path:
    """모드별 token 캐시 경로."""
    return TOKEN_CACHE_DIR / f"token_{creds.mode}.json"


def get_access_token(creds: KISCredentials) -> str | None:
    """KIS access token 발급. 디스크 캐시 + 1분 cooldown 회피.

    Returns:
        token string or None on failure.
    """
    cache_file = _token_cache_path(creds)

    # 1. 캐시 확인
    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as f:
                cached = json.load(f)
            issued_at = cached.get("issued_at", 0)
            if time.time() - issued_at < TOKEN_CACHE_TTL_SEC:
                return cached.get("access_token")
        except Exception:
            pass

    # 2. 새로 발급
    url = f"{creds.base_url}/oauth2/tokenP"
    req_payload = {
        "grant_type": "client_credentials",
        "appkey": creds.app_key,
        "appsecret": creds.app_secret,
    }
    try:
        resp = requests.post(url, json=req_payload, timeout=15)
        try:
            resp_payload = resp.json()
        except Exception:
            resp_payload = {}
        if _is_token_cooldown(resp_payload, resp.status_code):
            logger.warning("KIS 토큰 1분 cooldown — 캐시 대기 또는 1분 후 재시도")
            return None
        if resp.status_code != 200:
            logger.error("KIS 토큰 HTTP %d: %s", resp.status_code, resp_payload)
            return None
        token = resp_payload.get("access_token")
        if token:
            TOKEN_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps(
                    {
                        "access_token": token,
                        "issued_at": time.time(),
                        "expires_in": resp_payload.get("expires_in", 86400),
                    }
                )
            )
            return token
        logger.error("KIS 토큰 응답에 access_token 없음: %s", resp_payload)
    except Exception as e:
        logger.error("KIS 토큰 발급 실패: %s", e)
    return None


# ═══════════════════════════════════════════════════════
# 시세 조회
# ═══════════════════════════════════════════════════════


def _is_rate_limit(payload: dict) -> bool:
    """KIS 응답이 rate limit 거부인지 확인.

    KIS rate limit 응답 패턴 (실측 + 공식):
        - rt_cd='1' (에러)
        - msg_cd: None (해외 API) 또는 'EGW00201' (공식 코드, 일부 API)
        - msg1: '초당 거래건수를 초과하였습니다.'
    세 조건 중 하나라도 매칭되면 rate limit으로 판단.
    """
    if not isinstance(payload, dict):
        return False
    if str(payload.get("rt_cd", "")) != "1":
        return False
    msg_cd = str(payload.get("msg_cd", "") or "")
    if msg_cd == "EGW00201":
        return True
    msg = str(payload.get("msg1", "") or "")
    return "거래건수" in msg or "초당" in msg


def _is_token_cooldown(payload: dict, status_code: int) -> bool:
    """KIS 토큰 발급 1분 cooldown 응답 감지.

    KIS 토큰 API는 cooldown 시 보통 403 또는 200+에러 메시지로 응답.
    안전하게 두 케이스 모두 처리.
    """
    if status_code == 403:
        return True
    if not isinstance(payload, dict):
        return False
    err_desc = str(payload.get("error_description", "") or "")
    err_code = str(payload.get("error_code", "") or "")
    return "1분당" in err_desc or err_code == "EGW00133"


def _request_with_rate_limit_retry(url: str, headers: dict, params: dict, label: str) -> tuple[int | None, dict]:
    """KIS API 요청 — rate limit 시 1회 재시도. 명시적 2-call (loop natural-exit 회피).

    Returns:
        (status_code, payload) — 정상 / non-200 / 두 번째 시도도 rate-limited 인 경우
        (None, {}) — requests 예외 발생 시
    """
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        payload = resp.json() if resp.status_code == 200 else {}
        if _is_rate_limit(payload):
            time.sleep(KIS_RATE_LIMIT_RETRY_DELAY_SEC)
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            payload = resp.json() if resp.status_code == 200 else {}
        return resp.status_code, payload
    except Exception as e:
        logger.warning("KIS %s 요청 실패: %s", label, e)
        return None, {}


def inquire_price_kr(creds: KISCredentials, token: str, ticker: str) -> dict | None:
    """한국 종목 현재가 조회 (FHKST01010100).

    ticker: '005930.KS' → '005930' (suffix 제거).
    rate limit 발생 시 1초 대기 후 1회 재시도.
    """
    code = ticker.replace(".KS", "").replace(".KQ", "")
    url = f"{creds.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": creds.app_key,
        "appsecret": creds.app_secret,
        "tr_id": "FHKST01010100",
    }
    params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}

    status, payload = _request_with_rate_limit_retry(url, headers, params, f"한국 {ticker}")
    if status is None:
        return None
    if status != 200:
        logger.warning("KIS 한국 %s HTTP %d", ticker, status)
        return None
    data = payload.get("output", {})
    if not data or not data.get("stck_prpr"):
        logger.debug("KIS 한국 %s 빈 응답: rt_cd=%s msg=%s", ticker, payload.get("rt_cd"), payload.get("msg1"))
        return None
    if not float(data.get("stck_oprc", 0) or 0):
        # 시가 0 = 오늘 아직 체결이 없다(개장 전) 또는 거래정지. 현재가는 전일 종가일 뿐이라 봉이 아니다.
        # 방어적 가드다 — #1644 의 운영 27행은 이 경로가 아니라 pykrx(stock_kr.py) 가 썼다 (Codex 리뷰).
        logger.debug("KIS 한국 %s 시가 없음(개장 전/거래정지) — 봉으로 저장하지 않음", ticker)
        return None
    return {
        "ticker": ticker,
        "date": today_kst(),
        "open": float(data["stck_oprc"]),
        "high": float(data.get("stck_hgpr", 0) or 0),
        "low": float(data.get("stck_lwpr", 0) or 0),
        "close": float(data.get("stck_prpr", 0)),
        "volume": int(data.get("acml_vol", 0) or 0),
        "adj_close": float(data.get("stck_prpr", 0)),
    }


_NEW_YORK = ZoneInfo("America/New_York")
_US_REGULAR_OPEN = dtime(9, 30)


def us_session_date(now: datetime | None = None) -> str:
    """이 미국 시세가 속한 거래일 (YYYY-MM-DD, 뉴욕 달력).

    KIS 해외 현재가 응답에는 날짜가 없다. 예전에는 `today_kst()` 를 찍었는데, 미국 장이 열려
    있는 KST 아침은 뉴욕에선 아직 전날이라 같은 세션이 일일 수집기(yfinance, 미국 거래일)보다
    하루 뒤 날짜로 저장됐다 — 최신 날짜로 종목을 정렬하는 리더에서 SPY 만 하루 앞서 보인다
    (#1636). 뉴욕 시각으로 정규장 개장(09:30) 전이면 직전 세션의 종가이므로 전날, 이후면 당일.
    주말과 NYSE 휴장일은 직전 영업일로 당긴다.
    """
    et = (now or kst_now()).astimezone(_NEW_YORK)
    d = et.date()
    if et.time() < _US_REGULAR_OPEN:
        d -= timedelta(days=1)
    # 휴장 달력은 신선도 판정과 공유한다 (nuri/core/market_calendar.py, #1677)
    closed = nyse_holidays(d - timedelta(days=14), d)
    while d.weekday() >= 5 or d in closed:
        d -= timedelta(days=1)
    return d.isoformat()


def inquire_price_us(creds: KISCredentials, token: str, ticker: str) -> dict | None:
    """미국 종목 현재가 조회 (HHDFS00000300).

    EXCD: NAS (NASDAQ), NYS (NYSE), AMS (AMEX).
    rate limit 시 1초 대기 후 재시도. 같은 EXCD에서 빈 응답이면 다음 EXCD 시도.
    """
    url = f"{creds.base_url}/uapi/overseas-price/v1/quotations/price"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": creds.app_key,
        "appsecret": creds.app_secret,
        "tr_id": "HHDFS00000300",
    }
    for excd_idx, excd in enumerate(("NAS", "NYS", "AMS")):
        if excd_idx > 0:
            time.sleep(KIS_EXCD_RETRY_INTERVAL_SEC)  # EXCD 폴백 사이 rate limit 회피
        params = {"AUTH": "", "EXCD": excd, "SYMB": ticker}

        status, payload = _request_with_rate_limit_retry(url, headers, params, f"해외 {ticker} {excd}")
        if status is None or status != 200:
            continue  # 예외 / non-200 → 다음 EXCD
        data = payload.get("output", {})
        last = data.get("last", "")
        if last and float(last) > 0:
            return {
                "ticker": ticker,
                "date": us_session_date(),
                "open": float(data.get("open", 0) or 0),
                "high": float(data.get("high", 0) or 0),
                "low": float(data.get("low", 0) or 0),
                "close": float(last),
                "volume": int(data.get("tvol", 0) or 0),
                "adj_close": float(last),
            }
        # 빈 응답 → 다음 EXCD
    return None


# ═══════════════════════════════════════════════════════
# Collector
# ═══════════════════════════════════════════════════════


class KISRealtimeCollector(BaseCollector):
    """KIS Open API 실시간 시세 수집 (한국+미국)."""

    def __init__(self, mode: str = "prod"):
        super().__init__("kis_realtime")
        self.mode = mode
        self.creds: KISCredentials | None = None
        self.token: str | None = None

    def check_credentials(self) -> bool:
        """자격 증명 확인 (API 호출 X)."""
        self.creds = load_credentials(self.mode)
        if not self.creds:
            self.logger.error("KIS 자격 증명 없음 (.env 또는 config/kis/kis_devlp.yaml 확인)")
            return False
        masked_key = self.creds.app_key[:8] + "..." if len(self.creds.app_key) > 8 else "***"
        self.logger.info(
            "KIS 자격 증명 OK [%s] app_key=%s account=%s", self.mode, masked_key, self.creds.account or "(미설정)"
        )
        return True

    def collect(self, **kwargs) -> pd.DataFrame:
        """보유 종목 현재가 수집.

        KIS 실패 시 yfinance fallback (transient rate limit 등 회복).
        모드별 rate limit interval 자동 적용 (prod 0.4s, paper 1.0s).
        """
        if not self.check_credentials():
            return pd.DataFrame()
        self.token = get_access_token(self.creds)
        if not self.token:
            self.logger.error("KIS 토큰 발급 실패 — 1분 후 재시도 권장")
            return pd.DataFrame()

        # 모드별 rate limit interval (KIS 공지: prod 신규 3건/초, paper 더 낮음)
        interval = KIS_REQUEST_INTERVAL_PROD if self.mode == "prod" else KIS_REQUEST_INTERVAL_PAPER

        tickers = get_tickers()
        records = []
        kis_failures: list[str] = []
        for t in tickers:
            if t.endswith((".KS", ".KQ")):
                row = inquire_price_kr(self.creds, self.token, t)
            else:
                row = inquire_price_us(self.creds, self.token, t)
            if row:
                records.append({**row, "source": "kis"})
            else:
                kis_failures.append(t)
            time.sleep(interval)

        # yfinance fallback for KIS failures (transient rate limit, KIS 미지원 종목 등)
        yf_recovered = []
        if kis_failures:
            self.logger.warning(
                "KIS 시세 실패 %d종목, yfinance fallback 시도: %s", len(kis_failures), ", ".join(kis_failures)
            )
            yf_recovered = self._yfinance_fallback(kis_failures)
            # 폴백 행은 KIS 가 아니다 — 출처를 행마다 남긴다 (#1727)
            records.extend({**r, "source": "yfinance"} for r in yf_recovered)

        total = len(records)
        kis_count = total - len(yf_recovered)
        self.logger.info(
            "KIS 실시간 수집: %d/%d (KIS=%d, yfinance fallback=%d)",
            total,
            len(tickers),
            kis_count,
            len(yf_recovered),
        )
        return pd.DataFrame(records)

    @staticmethod
    def _yfinance_fallback(tickers: list[str]) -> list[dict]:
        """KIS 실패 종목을 yfinance로 보충 수집."""
        try:
            import yfinance as yf
        except ImportError:
            return []
        recovered = []
        for t in tickers:
            try:
                yf_ticker = t  # KS는 yfinance도 .KS suffix 사용
                hist = yf.Ticker(yf_ticker).history(period="2d")
                if hist.empty:
                    continue
                last = hist.iloc[-1]
                # 봉의 실제 거래일 (거래소 시간대) — today_kst() 는 미국 종목에 하루 앞선 날짜를 찍었다 (#1636)
                session = pd.Timestamp(hist.index[-1]).date().isoformat()
                recovered.append(
                    {
                        "ticker": t,
                        "date": session,
                        "open": float(last.get("Open", 0) or 0),
                        "high": float(last.get("High", 0) or 0),
                        "low": float(last.get("Low", 0) or 0),
                        "close": float(last.get("Close", 0)),
                        "volume": int(last.get("Volume", 0) or 0),
                        "adj_close": float(last.get("Close", 0)),
                    }
                )
            except Exception:
                continue
        return recovered

    @staticmethod
    def _drop_incomplete_bars_that_would_replace(data: pd.DataFrame) -> pd.DataFrame:
        """O/H/L 이 없는 행은 (ticker, date) 에 이미 봉이 있으면 쓰지 않는다 (#1636 P1).

        KIS 해외 현재가(HHDFS00000300)는 last/tvol 만 주어 open/high/low 가 0.0 이다.
        `upsert_prices` 는 INSERT OR REPLACE 라, 날짜를 바로잡은 뒤에는 이 행이 일일 수집기가
        이미 써 둔 완전한 yfinance 봉을 통째로 덮어 ATR·저가 리더가 0 을 본다. 봉이 없을 때만
        (장중 첫 관측) 들어가고, 있으면 그 봉이 정본이다.
        """
        if data.empty or not {"open", "high", "low"} <= set(data.columns):
            return data
        data = data.reset_index(drop=True)  # 라벨 조회가 유일 인덱스를 전제한다
        incomplete = (data[["open", "high", "low"]].fillna(0) == 0).all(axis=1)
        if not incomplete.any():
            return data
        keep = []
        for idx, row in data.iterrows():
            # 존재가 아니라 **완전성**을 본다 — 같은 날 이 수집기가 먼저 쓴 O/H/L 없는 행은 다음 관측이 갱신해야 한다
            if incomplete[idx] and query(
                "SELECT 1 FROM prices WHERE ticker = ? AND date = ? AND COALESCE(open, 0) != 0 LIMIT 1",
                (row["ticker"], row["date"]),
            ):
                logger.info("%s %s: 완전한 봉이 이미 있어 O/H/L 없는 현재가는 쓰지 않음", row["ticker"], row["date"])
                continue
            keep.append(idx)
        return data.loc[keep]

    def save(self, data: pd.DataFrame) -> int:
        if data.empty:
            return 0
        data = self._drop_incomplete_bars_that_would_replace(data)
        if data.empty:
            return 0
        return upsert_prices(data, source="kis")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="KIS Open API 실시간 시세")
    parser.add_argument("--mode", choices=["prod", "paper"], default="prod")
    parser.add_argument("--check-creds", action="store_true", help="자격 증명만 확인 (API 호출 X)")
    args = parser.parse_args()

    collector = KISRealtimeCollector(mode=args.mode)
    if args.check_creds:
        ok = collector.check_credentials()
        raise SystemExit(0 if ok else 1)
    collector.run()


if __name__ == "__main__":
    main()
