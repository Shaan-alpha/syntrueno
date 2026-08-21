"""Sole Gemini entry point for the Syntrueno swarm.

Everything the agents know about Gemini lives here. Two rules hold the design
together:

1. **This module never raises to its callers.** Every call returns an
   ``LlmResult``. When the model is unreachable the result carries ``ok=False``
   and a reason, so the calling agent can fall back to its heuristic path and
   report that it degraded rather than silently pretending.

2. **Every number is measured.** Latency comes from ``perf_counter`` and token
   counts come from the response's own ``usage_metadata``. Nothing here returns
   a constant dressed up as a measurement.

Model routing was verified by execution on 2026-08-22 against the project's
API key. ``gemini-2.5-*`` returns 404 for new keys and the Pro tier returns 429
on the free tier, so the two reachable tiers are:

===========  =======================  ==========  ==================================
Tier         Model                    Latency     Use
===========  =======================  ==========  ==================================
``fast``     gemini-3.1-flash-lite    ~8.5s       extraction, triage, routing
``reasoning`` gemini-3.6-flash        ~25.4s      root-cause diagnosis, judging
===========  =======================  ==========  ==================================

``gemini-3.6-flash`` rejects ``thinking_budget=0`` with a 400, so thinking is
left enabled on the reasoning tier and disabled only on the fast tier.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Type

from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

# Transient conditions worth retrying. 400/404 are configuration errors and a
# retry would only burn free-tier quota, so they fail fast.
_RETRYABLE_STATUS = (429, 500, 502, 503, 504)


class LlmTier(str, Enum):
    FAST = "fast"
    REASONING = "reasoning"


@dataclass
class LlmResult:
    """Outcome of a single Gemini call. Never an exception."""

    ok: bool
    value: Any = None
    model: str = ""
    tier: str = ""
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    attempts: int = 0
    degraded_reason: Optional[str] = None
    raw_text: Optional[str] = None
    fallback_used: bool = False
    preferred_model: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.thought_tokens

    def telemetry(self) -> dict:
        """Measured facts about this call, safe to surface in the UI."""
        return {
            "model": self.model,
            "tier": self.tier,
            "latency_ms": round(self.latency_ms, 2),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "thought_tokens": self.thought_tokens,
            "total_tokens": self.total_tokens,
            "attempts": self.attempts,
            "degraded": not self.ok,
            "degraded_reason": self.degraded_reason,
            "fallback_used": self.fallback_used,
            "preferred_model": self.preferred_model,
        }


def _status_of(exc: Exception) -> Optional[int]:
    """Best-effort HTTP status extraction from a google-genai exception."""
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    text = str(exc)
    for status in _RETRYABLE_STATUS + (400, 401, 403, 404):
        if text.startswith(f"{status} ") or f"'code': {status}" in text:
            return status
    return None


class GeminiClient:
    """Thin, defensive wrapper over ``google-genai``.

    The client is constructed lazily so that importing this module never
    requires a key. That keeps the offline test suite genuinely offline.
    """

    _client: Any = None
    _init_failed: bool = False

    # ---------------------------------------------------------------- setup

    @classmethod
    def _get_client(cls) -> Any:
        if cls._client is not None or cls._init_failed:
            return cls._client
        try:
            from google import genai
            from google.genai import types

            cls._client = genai.Client(
                api_key=settings.GEMINI_API_KEY,
                http_options=types.HttpOptions(
                    timeout=settings.LLM_TIMEOUT_SECONDS * 1000
                ),
            )
        except Exception as exc:  # pragma: no cover - import/credential failure
            logger.warning("Gemini client init failed: %s", exc)
            cls._init_failed = True
            cls._client = None
        return cls._client

    @classmethod
    def reset(cls) -> None:
        """Drop the cached client. Used by tests that flip settings."""
        cls._client = None
        cls._init_failed = False

    @classmethod
    def is_available(cls) -> bool:
        return settings.llm_available

    @classmethod
    def model_for(cls, tier: LlmTier) -> str:
        return (
            settings.REASONING_MODEL
            if tier == LlmTier.REASONING
            else settings.FAST_MODEL
        )

    # ----------------------------------------------------------- public API

    @classmethod
    def generate_structured(
        cls,
        prompt: str,
        schema: Type[BaseModel],
        system_instruction: str = "",
        tier: LlmTier = LlmTier.REASONING,
        temperature: float = 0.0,
    ) -> LlmResult:
        """Ask Gemini for JSON matching ``schema``.

        On success ``result.value`` is a validated instance of ``schema``.
        """
        return cls._invoke(
            prompt=prompt,
            system_instruction=system_instruction,
            tier=tier,
            temperature=temperature,
            schema=schema,
        )

    @classmethod
    def generate_text(
        cls,
        prompt: str,
        system_instruction: str = "",
        tier: LlmTier = LlmTier.FAST,
        temperature: float = 0.2,
    ) -> LlmResult:
        """Ask Gemini for free text. ``result.value`` is a ``str``."""
        return cls._invoke(
            prompt=prompt,
            system_instruction=system_instruction,
            tier=tier,
            temperature=temperature,
            schema=None,
        )

    # ------------------------------------------------------------ internals

    @classmethod
    def _invoke(
        cls,
        prompt: str,
        system_instruction: str,
        tier: LlmTier,
        temperature: float,
        schema: Optional[Type[BaseModel]],
    ) -> LlmResult:
        model = cls.model_for(tier)

        if not cls.is_available():
            reason = (
                "simulation_mode"
                if settings.SIMULATION_MODE
                else "no_api_key"
            )
            return LlmResult(
                ok=False, model=model, tier=tier.value, degraded_reason=reason
            )

        client = cls._get_client()
        if client is None:
            return LlmResult(
                ok=False,
                model=model,
                tier=tier.value,
                degraded_reason="client_init_failed",
            )

        from google.genai import types

        base_config: dict = {"temperature": temperature}
        if system_instruction:
            base_config["system_instruction"] = system_instruction
        if schema is not None:
            base_config["response_mime_type"] = "application/json"
            base_config["response_schema"] = schema

        started = time.perf_counter()
        last_reason = "unknown"
        total_attempts = 0
        chain = settings.model_chain(tier.value)

        for chain_index, candidate in enumerate(chain):
            config_kwargs = dict(base_config)

            # Only the lite models accept a zero thinking budget. The full Flash
            # models reject thinking_budget=0 with a 400, so it is applied by
            # capability rather than by tier.
            if "lite" in candidate and settings.FAST_THINKING_BUDGET == 0:
                config_kwargs["thinking_config"] = types.ThinkingConfig(
                    thinking_budget=0
                )

            for attempt in range(1, settings.LLM_MAX_RETRIES + 1):
                total_attempts += 1
                try:
                    response = client.models.generate_content(
                        model=candidate,
                        contents=prompt,
                        config=types.GenerateContentConfig(**config_kwargs),
                    )
                    usage = getattr(response, "usage_metadata", None)
                    text = response.text or ""

                    value: Any = text
                    if schema is not None:
                        value = schema.model_validate_json(text)

                    if chain_index > 0:
                        logger.info(
                            "Gemini served by fallback %s (preferred %s unavailable)",
                            candidate, chain[0],
                        )

                    return LlmResult(
                        ok=True,
                        value=value,
                        model=candidate,
                        tier=tier.value,
                        latency_ms=(time.perf_counter() - started) * 1000,
                        input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                        output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
                        thought_tokens=getattr(usage, "thoughts_token_count", 0) or 0,
                        attempts=total_attempts,
                        raw_text=text,
                        fallback_used=chain_index > 0,
                        preferred_model=chain[0],
                    )

                except Exception as exc:
                    status = _status_of(exc)
                    last_reason = f"{type(exc).__name__}:{status or 'unknown'}"

                    # A 429 on the free tier is usually a *daily* cap, which no
                    # amount of backoff will clear. Move to the next model at
                    # once rather than sleeping against a wall. Likewise a
                    # 400/404 means this model rejects the request shape.
                    if status in (400, 401, 403, 404, 429):
                        logger.info(
                            "Gemini %s unavailable (%s); advancing to next model",
                            candidate, status,
                        )
                        break

                    if attempt == settings.LLM_MAX_RETRIES:
                        logger.warning(
                            "Gemini %s exhausted retries: %s",
                            candidate, str(exc)[:160],
                        )
                        break

                    # Jittered backoff so concurrent agents hitting the same
                    # transient failure do not retry in lockstep.
                    time.sleep((2 ** (attempt - 1)) + random.uniform(0, 0.5))

        return LlmResult(
            ok=False,
            model=chain[0],
            tier=tier.value,
            latency_ms=(time.perf_counter() - started) * 1000,
            attempts=total_attempts,
            degraded_reason=f"all_models_exhausted:{last_reason}",
            preferred_model=chain[0],
        )
