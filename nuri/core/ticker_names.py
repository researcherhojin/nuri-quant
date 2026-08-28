"""한국 종목코드 → 종목명 해석.

.KS 티커(예: 132030.KS)는 사람이 알아볼 수 없으므로 종목명을 조회한다.
1차: portfolio.metadata.note (사용자가 YAML에 입력한 이름)
2차: config/kr_ticker_names.json 로컬 맵 (KOSPI200 정적 — network-free)
3차: pykrx get_market_ticker_name (1·2차 미스 시에만, 주식 only)
US 티커(MSFT, TSLA 등)는 이미 식별 가능하므로 None 반환.

⚠️ 2차 로컬 맵이 핵심: /tickers/search 가 KR 이름 검색 시 수백 ticker 를
순회하는데, 맵 없이는 ticker 당 live pykrx 호출 → 요청당 수백 네트워크 콜
(지연/hang/CI flaky). 맵은 요청 경로를 network-free 로 만든다.
config/kr_ticker_names.json 갱신: universe-sync 로 KOSPI200 변경 시 재생성.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_KR_NAMES_PATH = Path(__file__).resolve().parents[2] / "config" / "kr_ticker_names.json"


@lru_cache(maxsize=1)
def _load_kr_name_map() -> dict[str, str]:
    """config/kr_ticker_names.json 1회 로드 (KOSPI200 정적 맵). 없으면 빈 dict."""
    try:
        return json.loads(_KR_NAMES_PATH.read_text(encoding="utf-8"))
    except Exception as e:  # 파일 부재/파싱 실패 시 graceful — pykrx fallback 으로 흐름
        logger.debug("KR name map load failed: %s", e)
        return {}


def is_kr_ticker(ticker: str) -> bool:
    """KR(한국) 종목 여부 — KOSPI(.KS) + KOSDAQ(.KQ). 통화/지역 게이트용 (#764).

    .KS 만 검사하면 .KQ(KOSDAQ) 홀딩이 fundamentals 는 KR, 통화/PnL 은 USD 로
    split-brain 오변환된다. 통화/지역 분기는 모두 이 helper 를 경유한다.
    """
    return str(ticker).endswith((".KS", ".KQ"))


@lru_cache(maxsize=500)
def get_ticker_name_local(ticker: str) -> str | None:
    """1·2차만 조회하는 **network-free** 변형 — 요청 경로 전용 (#1255).

    `/api/tickers/search` 는 결과가 8건 미만이면 KOSPI200 **203개 전 티커**에
    이 함수를 부른다. 3차 pykrx 가 붙어 있으면 그 요청 하나가 네트워크를 타고,
    CI 처럼 맵이 없는 환경에서는 첫 호출이 KRX 전체 티커 목록을 받느라 4.64s 를
    쓴다 (2026-08-28 실측). 그 콜드스타트가 Playwright 의 15s 예산 안에 들어갈지가
    실행마다 갈려서 `/explore` 검색 스펙 2종이 main 7런 중 2런 실패했다 (#1255).

    프로덕션은 이 분리로 아무것도 잃지 않는다 — dev·mini 둘 다 로컬 맵이 있어
    2차에서 해결된다. 맵에 없는 소수 종목은 pykrx 를 기다렸다가 코드를 보여주는
    대신 **즉시** 코드를 보여준다.

    배치·알림 경로는 `get_ticker_name` 을 그대로 쓴다 — 거기는 보유 종목 단위라
    호출이 소수이고, 맵에 없는 신규 보유를 pykrx 로 self-heal 하는 게 이득이다.
    """
    if not ticker.endswith((".KS", ".KQ")):
        return None

    # 1차: DB portfolio metadata에서 name/note 필드 조회.
    # `name` 명시값 우선. `note` 는 보통 "<canonical> — <buy thesis>" 패턴이라
    # 첫 dash 앞부분만 canonical name 으로 본다 (그렇지 않으면 brief 가
    # 매수 narrative 전체를 ticker 자리에 표시해 가독성이 무너짐).
    try:
        from nuri.core.db import query

        rows = query(
            "SELECT metadata FROM portfolio WHERE ticker = ? AND metadata IS NOT NULL LIMIT 1",
            (ticker,),
        )
        if rows:
            meta = json.loads(rows[0]["metadata"])
            name = meta.get("name")
            if name:
                return str(name).strip()
            note = meta.get("note")
            if note:
                for sep in (" — ", " - ", "—"):
                    if sep in note:
                        return note.split(sep, 1)[0].strip()
                return note[:24].strip()
    except Exception as e:
        logger.debug("DB name lookup failed for %s: %s", ticker, e)

    # 2차: 로컬 KOSPI200 맵 (network-free — search 요청 경로 보호)
    return _load_kr_name_map().get(ticker) or None


@lru_cache(maxsize=500)
def get_ticker_name(ticker: str) -> str | None:
    """한국 종목 이름 반환. US 티커는 None. 1·2차 미스 시 pykrx(네트워크) fallback.

    요청 경로에서는 `get_ticker_name_local` 을 쓴다 (#1255) — 아래 3차가 네트워크다.
    """
    name = get_ticker_name_local(ticker)
    if name or not ticker.endswith((".KS", ".KQ")):
        return name

    # 3차: pykrx 주식 이름 조회 (1·2차 미스 시에만 — ETF/맵외 종목 fallback)
    code = ticker.replace(".KS", "").replace(".KQ", "")
    try:
        from pykrx import stock as krx

        name = krx.get_market_ticker_name(code)
        return name if name else None
    except Exception as e:
        logger.debug("pykrx name lookup failed for %s: %s", ticker, e)
        return None
