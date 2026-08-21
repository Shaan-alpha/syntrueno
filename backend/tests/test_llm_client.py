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


def test_does_not_retry_configuration_errors(monkeypatch):
    """A 404 means a wrong model name. Retrying only burns free-tier quota."""
    monkeypatch.setattr(settings, "SIMULATION_MODE", False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")

    fake = MagicMock()
    fake.models.generate_content.side_effect = Exception(
        "404 NOT_FOUND. {'error': {'code': 404}}"
    )
    monkeypatch.setattr(GeminiClient, "_client", fake)

    result = GeminiClient.generate_structured("x", JudgeEvaluation)

    assert result.ok is False
    assert fake.models.generate_content.call_count == 1


def test_exhausted_retries_return_a_result_not_an_exception(monkeypatch):
    monkeypatch.setattr(settings, "SIMULATION_MODE", False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "LLM_MAX_RETRIES", 2)

    fake = MagicMock()
    fake.models.generate_content.side_effect = Exception(
        "429 RESOURCE_EXHAUSTED. {'error': {'code': 429}}"
    )
    monkeypatch.setattr(GeminiClient, "_client", fake)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    result = GeminiClient.generate_structured("x", JudgeEvaluation)

    assert result.ok is False
    assert result.attempts == 2
    assert "429" in result.degraded_reason
