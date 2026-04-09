"""
nuri.llm.openai_client — single chokepoint for all OpenAI API calls (#152 Step 1).

STRATEGY.md §4.4.3 mandates that every external LLM call goes through this
module. Direct `import openai` elsewhere in `nuri/` is forbidden so that:

1. Audit logging is uniform — every call writes a row to `external_llm_calls`
   with token counts and latency, but **never the content**. This makes the
   audit log itself safe to keep on disk and inspect.
2. Opt-out is centralized — the user can disable all external LLM traffic
   with `NURI_DISABLE_EXTERNAL_LLM=1` and any caller automatically becomes
   degraded to its own fallback (or raises if no fallback exists).
3. Failure mode is uniform — the wrapper raises explicit, typed exceptions
   on every failure path so callers can decide their own degradation
   strategy. The wrapper itself does **not** silently fall back to anything.
4. Provider/model substitution — when a future PR adds another provider
   (Anthropic, Gemini, local Ollama as secondary, ...) it slots in here.

The current §4.4.3 whitelist permits **public RSS headline classification
only** (Tier 0 data). Sending Tier 1 (user narrative) or Tier 2 (portfolio)
data through this wrapper is a STRATEGY violation that requires a separate
PR to enable. The wrapper does not enforce that distinction at runtime —
that's the caller's responsibility — but the wrapper docstrings and the
STRATEGY.md table are the single source of truth.

Usage:

    from nuri.llm.openai_client import get_client, ExternalLLMDisabled

    try:
        client = get_client()
        result = client.chat_json(
            system="Classify this headline...",
            user="Headline: ...",
            model="gpt-5.4-nano",
        )
    except ExternalLLMDisabled:
        # NURI_DISABLE_EXTERNAL_LLM=1 — caller falls back
        ...
    except ExternalLLMUnavailable:
        # Network/API failure — caller falls back
        ...
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

from dotenv import load_dotenv

from nuri.core.db import log_external_llm_call

load_dotenv()

logger = logging.getLogger(__name__)

# Provider identity (currently single-provider; new providers add their own)
PROVIDER = "openai"
DEFAULT_MODEL = "gpt-5.4-nano"


class ExternalLLMError(Exception):
    """Base for all external LLM errors. Callers should catch this."""


class ExternalLLMDisabled(ExternalLLMError):
    """Raised when NURI_DISABLE_EXTERNAL_LLM=1 is set.

    Callers should treat this as 'feature unavailable, fall back to local-only
    behavior'. Not an error per se — it's an explicit user opt-out.
    """


class ExternalLLMUnavailable(ExternalLLMError):
    """Raised when the API is unreachable, returns 5xx, or auth fails.

    Callers should treat this as transient and either retry or fall back.
    The wrapper does NOT retry internally — that's the caller's policy.
    """


class ExternalLLMResponseError(ExternalLLMError):
    """Raised when the API returns a successful response that we can't parse.

    Examples: malformed JSON when JSON mode requested, missing required
    fields. Different from ExternalLLMUnavailable because the network worked
    fine — the model just gave us garbage.
    """


def is_disabled() -> bool:
    """True if external LLM is opted out via env var."""
    val = os.getenv("NURI_DISABLE_EXTERNAL_LLM", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def has_credentials() -> bool:
    """True if OPENAI_API_KEY is present (not necessarily valid)."""
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


class OpenAIClient:
    """Thin wrapper around the OpenAI Python SDK with mandatory audit logging.

    Stateless except for a lazily-constructed SDK client object. Safe to
    instantiate once per process or per call.
    """

    def __init__(self, *, default_model: str = DEFAULT_MODEL):
        self.default_model = default_model
        self._sdk_client: Any = None  # lazy

    def _ensure_sdk(self) -> Any:
        if self._sdk_client is not None:
            return self._sdk_client
        if is_disabled():
            raise ExternalLLMDisabled(
                "NURI_DISABLE_EXTERNAL_LLM is set — external LLM calls are "
                "opted out. Caller should fall back to local behavior."
            )
        if not has_credentials():
            raise ExternalLLMUnavailable(
                "OPENAI_API_KEY missing from environment. Set it in .env or "
                "set NURI_DISABLE_EXTERNAL_LLM=1 to opt out."
            )
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ExternalLLMUnavailable(
                f"openai SDK not installed: {e}"
            ) from e
        self._sdk_client = OpenAI()
        return self._sdk_client

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 256,
        db_path: Optional[Any] = None,
    ) -> dict:
        """Call chat.completions in JSON mode and return the parsed dict.

        Logs one row to external_llm_calls regardless of success/failure
        (so monitoring sees error rates too). content is never logged.

        Raises:
            ExternalLLMDisabled: opt-out via env var
            ExternalLLMUnavailable: network/auth/SDK install failure
            ExternalLLMResponseError: API returned 200 but body was unparseable
        """
        sdk = self._ensure_sdk()  # may raise ExternalLLMDisabled / Unavailable
        chosen_model = model or self.default_model
        endpoint = "chat.completions"

        t0 = time.monotonic()
        try:
            # gpt-5.x series renamed max_tokens → max_completion_tokens.
            # The new parameter is the canonical one for current models;
            # older models still accept it as an alias.
            resp = sdk.chat.completions.create(
                model=chosen_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=temperature,
                max_completion_tokens=max_tokens,
            )
        except Exception as e:
            latency_ms = int((time.monotonic() - t0) * 1000)
            error_type = type(e).__name__
            try:
                log_external_llm_call(
                    provider=PROVIDER, model=chosen_model, endpoint=endpoint,
                    latency_ms=latency_ms, success=False, error_type=error_type,
                    db_path=db_path,
                )
            except Exception:  # noqa: BLE001 — audit log failure must not mask the real error
                logger.debug("audit log write failed", exc_info=True)
            raise ExternalLLMUnavailable(
                f"OpenAI {endpoint} call failed: {error_type}: {str(e)[:200]}"
            ) from e

        latency_ms = int((time.monotonic() - t0) * 1000)
        usage = resp.usage
        try:
            log_external_llm_call(
                provider=PROVIDER,
                model=chosen_model,
                endpoint=endpoint,
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
                latency_ms=latency_ms,
                success=True,
                error_type=None,
                db_path=db_path,
            )
        except Exception:  # noqa: BLE001
            logger.debug("audit log write failed", exc_info=True)

        # Parse JSON body
        raw = resp.choices[0].message.content or "{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ExternalLLMResponseError(
                f"OpenAI {chosen_model} returned non-JSON in JSON mode: "
                f"{raw[:100]!r}"
            ) from e


_singleton: Optional[OpenAIClient] = None


def get_client() -> OpenAIClient:
    """Process-wide singleton. Constructs lazily so import is free."""
    global _singleton
    if _singleton is None:
        _singleton = OpenAIClient()
    return _singleton
