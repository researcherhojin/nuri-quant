"""시그널 설정 로더 — config/signals.yaml에서 시그널 메타데이터/임계값을 로드.

사용법:
    from nuri.core.signal_config import SIGNAL_CONFIG, get_signal_params, get_signal_meta

    params = get_signal_params("near_52w_low_bounce")
    proximity = params.get("proximity_pct", 0.10)
    meta = get_signal_meta("near_52w_low_bounce")
    if meta.get("enabled", True):
        ...

설계 원칙 (STRATEGY.md §2.2 mechanical execution):
    - 임계값/분류는 본 모듈 → YAML → SIGNAL_CONFIG에서 읽음
    - detector 함수 자체는 코드 (실행 가능 로직)
    - signal_backtest.py의 SIGNAL_DEFINITIONS는 YAML + detectors로 빌드
"""

from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "signals.yaml"


def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


SIGNAL_CONFIG: dict = _load_config()


def get_signal_meta(signal_id: str) -> dict:
    """시그널 메타데이터 (description, type, hold_days, enabled) 반환.

    없는 시그널 → 빈 dict (기본값으로 graceful degrade).
    """
    return SIGNAL_CONFIG.get("signals", {}).get(signal_id, {})


def get_signal_params(signal_id: str) -> dict:
    """시그널의 임계값/파라미터 dict 반환."""
    return get_signal_meta(signal_id).get("params", {}) or {}


def is_enabled(signal_id: str) -> bool:
    """시그널 활성화 여부. 미정의 시 True (안전한 기본값)."""
    return bool(get_signal_meta(signal_id).get("enabled", True))


def list_buy_signals() -> set[str]:
    """type=BUY로 분류된 모든 시그널 ID."""
    return {
        sid
        for sid, meta in SIGNAL_CONFIG.get("signals", {}).items()
        if meta.get("type") == "BUY" and meta.get("enabled", True)
    }


def list_sell_signals() -> set[str]:
    """type=SELL로 분류된 모든 시그널 ID."""
    return {
        sid
        for sid, meta in SIGNAL_CONFIG.get("signals", {}).items()
        if meta.get("type") == "SELL" and meta.get("enabled", True)
    }


def is_actionable(signal_id: str) -> bool:
    """시그널이 candidate 추천에 포함되어야 하는가 (PR C, codex #3).

    YAML 의 `actionable: false` 로 설정된 SHADOW 신호 (STRATEGY §2.6 Surface 단계)
    는 scorecard backtest 에는 들어가지만 `candidates.py` 가 제외.
    Downstream (confidence/tier) 에 간접 반영되지 않도록 구조적 분리 — codex
    Plan consult Biggest Risk.

    미정의 시 True (기존 signal 은 전부 actionable 로 기본 동작 유지).
    """
    return bool(get_signal_meta(signal_id).get("actionable", True))


def list_shadow_signals() -> set[str]:
    """SHADOW (`actionable: false`) 신호 ID 집합.

    PR C (codex bubble-bear #3) 로 도입된 crash precursor 신호들 — UI surface
    용으로만 사용, candidates/confidence 에 영향 없음. scorecard 집계는 계속.
    """
    return {
        sid
        for sid, meta in SIGNAL_CONFIG.get("signals", {}).items()
        if meta.get("enabled", True) and meta.get("actionable", True) is False
    }
