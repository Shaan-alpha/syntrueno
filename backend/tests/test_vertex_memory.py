"""The Memory Bank client must degrade, never raise.

It sits inside the incident path. An exception here would take down incident
triage to save a recall that the Firestore fallback can serve anyway, which is
the wrong way round: the swarm losing its memory of a service is a worse day
than the swarm losing the incident in front of it.

Same contract as app/llm/gemini.py and app/storage/firestore_backend.py.
"""

import httpx
import pytest

from app.config import settings
from app.memory.vertex_memory import VertexMemory


@pytest.fixture
def enabled(monkeypatch):
    """A configured client with the credential fetch stubbed out.

    google.auth.default() does credential discovery, which reads files and can
    reach the metadata server. Stubbing the token keeps these tests offline
    while leaving every line of request handling under test.
    """
    monkeypatch.setattr(settings, "VERTEX_MEMORY_ENABLED", True)
    monkeypatch.setattr(settings, "AGENT_ENGINE_ID", "1234567890")
    monkeypatch.setattr(VertexMemory, "_token", classmethod(lambda cls: "fake"))
    VertexMemory.reset()
    yield
    VertexMemory.reset()


def test_a_disabled_client_reports_unavailable_without_calling_out():
    """Absent configuration is not an error, and must not look like one."""
    VertexMemory.reset()
    result = VertexMemory.recall({"service_id": "svc"}, "why did it fail")
    assert result.ok is False
    assert result.degraded_reason == "memory_bank_disabled"
    assert result.memories == []


def test_a_transport_error_degrades_rather_than_raising(enabled, monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.HTTPError("connection reset")

    monkeypatch.setattr(httpx, "post", boom)
    result = VertexMemory.recall({"service_id": "svc"}, "query")
    assert result.ok is False
    assert "HTTPError" in result.degraded_reason


def test_an_error_status_degrades_and_names_the_code(enabled, monkeypatch):
    class Response:
        status_code = 503

        def json(self):  # pragma: no cover - must not be reached
            raise AssertionError("a 503 body must not be parsed")

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Response())
    result = VertexMemory.recall({"service_id": "svc"}, "query")
    assert result.ok is False
    assert result.degraded_reason == "http_503"


def test_malformed_json_degrades_rather_than_raising(enabled, monkeypatch):
    """A 200 carrying junk is the case a status check alone would miss."""

    class Response:
        status_code = 200

        def json(self):
            raise ValueError("not json at all")

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Response())
    result = VertexMemory.recall({"service_id": "svc"}, "query")
    assert result.ok is False
    assert result.memories == []


def test_a_successful_recall_returns_facts_with_their_distance(enabled, monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            return {
                "retrievedMemories": [
                    {
                        "memory": {
                            "fact": "canary OOMKilled at 512Mi",
                            "scope": {"service_id": "svc"},
                            "createTime": "2026-08-26T05:27:38Z",
                        },
                        "distance": 0.84,
                    }
                ]
            }

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Response())
    result = VertexMemory.recall({"service_id": "svc"}, "out of memory")

    assert result.ok is True
    assert result.memories[0]["fact"] == "canary OOMKilled at 512Mi"
    assert result.memories[0]["distance"] == 0.84
    assert result.memories[0]["recorded_at"] == "2026-08-26T05:27:38Z"


def test_recall_asks_for_a_semantic_search(enabled, monkeypatch):
    """Scope alone returns everything for the service in insertion order.

    The reason to make this call at all is that it matches on meaning, so the
    query has to actually be sent.
    """
    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {"retrievedMemories": []}

    def capture(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return Response()

    monkeypatch.setattr(httpx, "post", capture)
    VertexMemory.recall({"service_id": "svc"}, "container keeps dying", limit=2)

    assert captured["url"].endswith("/memories:retrieve")
    assert captured["json"]["similaritySearchParams"]["searchQuery"] == (
        "container keeps dying"
    )
    assert captured["json"]["similaritySearchParams"]["topK"] == 2


def test_a_failed_write_returns_false_rather_than_raising(enabled, monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ReadTimeout("too slow")

    monkeypatch.setattr(httpx, "post", boom)
    assert VertexMemory.record("a fact", {"service_id": "svc"}) is False


def test_a_successful_write_reports_that_it_landed(enabled, monkeypatch):
    class Response:
        status_code = 200

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Response())
    assert VertexMemory.record("a fact", {"service_id": "svc"}) is True


def test_a_disabled_client_does_not_pretend_a_write_landed():
    VertexMemory.reset()
    assert VertexMemory.record("a fact", {"service_id": "svc"}) is False


def test_the_engine_url_uses_the_agent_engine_location_not_the_gemini_one(
    enabled, monkeypatch
):
    """VERTEX_LOCATION is "global" for Gemini and Agent Engine 404s there.

    Verified by execution 2026-08-26. Reusing it would break every memory call
    while looking like a configuration typo.
    """
    monkeypatch.setattr(settings, "VERTEX_LOCATION", "global")
    monkeypatch.setattr(settings, "AGENT_ENGINE_LOCATION", "us-central1")

    base = VertexMemory._base()
    assert base.startswith("https://us-central1-aiplatform.googleapis.com/")
    assert "global" not in base
