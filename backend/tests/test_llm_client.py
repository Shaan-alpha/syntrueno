"""The Gemini wrapper must degrade honestly and never raise to its callers."""

import pytest
from unittest.mock import MagicMock, patch

from app.config import settings
from app.llm.gemini import GeminiClient, LlmResult, LlmTier, _status_of
from app.models import JudgeEvaluation


@pytest.fixture(autouse=True)
def _reset_client():
    GeminiClient.reset()
    yield
    GeminiClient.reset()


# --------------------------------------------------------------- offline path

def test_simulation_mode_never_calls_the_api(monkeypatch):
    monkeypatch.setattr(settings, "SIMULATION_MODE", True)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "irrelevant-when-simulating")

    result = GeminiClient.generate_text("diagnose this")

    assert result.ok is False
    assert result.degraded_reason == "simulation_mode"
    assert result.value is None


def test_missing_key_degrades_rather_than_raising(monkeypatch):
    monkeypatch.setattr(settings, "SIMULATION_MODE", False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)

    result = GeminiClient.generate_structured("score this", JudgeEvaluation)

    assert result.ok is False
    assert result.degraded_reason == "no_api_key"


def test_tier_selects_the_configured_model():
    assert GeminiClient.model_for(LlmTier.FAST) == settings.FAST_MODEL
    assert GeminiClient.model_for(LlmTier.REASONING) == settings.REASONING_MODEL
    assert settings.FAST_MODEL != settings.REASONING_MODEL


# ------------------------------------------------------------------ telemetry

def test_telemetry_reports_measured_values_not_constants():
    result = LlmResult(
        ok=True, model="gemini-3.6-flash", tier="reasoning",
        latency_ms=1234.567, input_tokens=100, output_tokens=50,
        thought_tokens=572, attempts=1,
    )
    t = result.telemetry()

    assert t["latency_ms"] == 1234.57
    assert t["total_tokens"] == 722
    assert t["degraded"] is False


def test_failed_result_marks_itself_degraded():
    t = LlmResult(ok=False, degraded_reason="ClientError:429").telemetry()

    assert t["degraded"] is True
    assert t["degraded_reason"] == "ClientError:429"


# -------------------------------------------------------------- retry policy

@pytest.mark.parametrize(
    "message, expected",
    [
        ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429}}", 429),
        ("503 UNAVAILABLE. {'error': {'code': 503}}", 503),
        ("404 NOT_FOUND. {'error': {'code': 404}}", 404),
        ("something entirely unparseable", None),
    ],
)
def test_status_extraction(message, expected):
    assert _status_of(Exception(message)) == expected


def test_retries_transient_failures_then_succeeds(monkeypatch):
    monkeypatch.setattr(settings, "SIMULATION_MODE", False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "LLM_MAX_RETRIES", 3)

    good = MagicMock()
    good.text = '{"score":9.0,"is_approved":true,"critique":"fine"}'
    good.usage_metadata = MagicMock(
        prompt_token_count=10, candidates_token_count=5, thoughts_token_count=0
    )

    fake = MagicMock()
    fake.models.generate_content.side_effect = [
        Exception("503 UNAVAILABLE. {'error': {'code': 503}}"),
        good,
    ]
    monkeypatch.setattr(GeminiClient, "_client", fake)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    result = GeminiClient.generate_structured("x", JudgeEvaluation)

    assert result.ok is True
    assert result.attempts == 2
    assert result.value.score == 9.0


def test_a_config_error_advances_the_chain_without_retrying_one_model(monkeypatch):
    """A 404 means that model rejects the request. Retrying it burns quota.

    Each candidate gets exactly one attempt, then the chain advances.
    """
    monkeypatch.setattr(settings, "SIMULATION_MODE", False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")

    fake = MagicMock()
    fake.models.generate_content.side_effect = Exception(
        "404 NOT_FOUND. {'error': {'code': 404}}"
    )
    monkeypatch.setattr(GeminiClient, "_client", fake)

    result = GeminiClient.generate_structured("x", JudgeEvaluation)
    chain_length = len(settings.model_chain("reasoning"))

    assert result.ok is False
    assert fake.models.generate_content.call_count == chain_length


def test_a_daily_quota_cap_falls_through_to_the_next_model(monkeypatch):
    """The free tier caps the thinking Flash models at 20 requests/day.

    Backing off against a daily cap never clears it, so a 429 must advance to
    the next model immediately. This is what keeps a demo alive once the
    preferred model's daily budget is spent.
    """
    monkeypatch.setattr(settings, "SIMULATION_MODE", False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")

    good = MagicMock()
    good.text = '{"score":9.0,"is_approved":true,"critique":"fine"}'
    good.usage_metadata = MagicMock(
        prompt_token_count=10, candidates_token_count=5, thoughts_token_count=0
    )

    fake = MagicMock()
    # First candidate is capped for the day; second one serves.
    fake.models.generate_content.side_effect = [
        Exception("429 RESOURCE_EXHAUSTED. {'error': {'code': 429}}"),
        good,
    ]
    monkeypatch.setattr(GeminiClient, "_client", fake)

    result = GeminiClient.generate_structured("x", JudgeEvaluation)
    chain = settings.model_chain("reasoning")

    assert result.ok is True
    assert result.fallback_used is True
    assert result.model == chain[1]
    assert result.preferred_model == chain[0]
    # One attempt each: no backoff was spent on the capped model.
    assert fake.models.generate_content.call_count == 2


def test_exhausting_every_model_returns_a_result_not_an_exception(monkeypatch):
    monkeypatch.setattr(settings, "SIMULATION_MODE", False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")

    fake = MagicMock()
    fake.models.generate_content.side_effect = Exception(
        "429 RESOURCE_EXHAUSTED. {'error': {'code': 429}}"
    )
    monkeypatch.setattr(GeminiClient, "_client", fake)

    result = GeminiClient.generate_structured("x", JudgeEvaluation)

    assert result.ok is False
    assert result.degraded_reason.startswith("all_models_exhausted")
    assert "429" in result.degraded_reason


def test_the_reasoning_chain_pools_several_daily_budgets():
    """The whole point of the chain: 20/day on one model is not enough to
    develop against, let alone record a video."""
    chain = settings.model_chain("reasoning")
    assert len(chain) >= 3
    assert chain[0] == settings.REASONING_MODEL
    assert len(chain) == len(set(chain)), "a model must not appear twice"
    assert any("lite" in m for m in chain), (
        "the chain must end at a high-quota model so it cannot run dry"
    )
