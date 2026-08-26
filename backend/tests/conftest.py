"""Shared test fixtures.

The suite is offline by construction: it must pass with no API key, no Google
Cloud credentials, and no network. A judge cloning the repository runs `pytest`
and gets a green suite in about a second without configuring anything.

That property is enforced here rather than assumed. Developer `.env` files
enable Firestore and carry a real Gemini key, and without these overrides the
suite silently starts making network calls — which showed up as the runtime
going from 1s to 59s.
"""

import pytest

from app.config import settings
from app.llm.gemini import GeminiClient
from app.llm.gemma import GemmaScreen
from app.memory.vertex_memory import VertexMemory
from app.telemetry.tracing import Tracing
from app.security.model_armor import ModelArmorShield
from app.storage.firestore_backend import FirestoreBackend


@pytest.fixture(autouse=True)
def offline_by_default(monkeypatch):
    """Force every external dependency off, whatever the local .env says."""
    monkeypatch.setattr(settings, "SIMULATION_MODE", True)
    monkeypatch.setattr(settings, "FIRESTORE_ENABLED", False)
    monkeypatch.setattr(settings, "USE_REAL_MODEL_ARMOR", False)
    monkeypatch.setattr(settings, "REMEDIATION_DRY_RUN", True)

    # Pinned for the same reason as the rest: a deployed .env sets this true,
    # and the backend it selects changes both the auth path and the degraded
    # reason a test asserts on. Tests that want Vertex opt in explicitly.
    monkeypatch.setattr(settings, "USE_VERTEX_AI", False)

    # The event-driven ingest path reaches the swarm with no human in the
    # loop. It stays shut in tests unless a test opens it deliberately.
    monkeypatch.setattr(settings, "PUBSUB_INGEST_ENABLED", False)

    # Gemma runs on the AI Studio key and is a real network call. Off here for
    # the same reason as every other external dependency.
    monkeypatch.setattr(settings, "USE_GEMMA_SCREEN", False)

    # Memory Bank is a real network call sitting inside the incident path, and
    # google.auth.default() does credential discovery before the request is
    # even made. Off here; tests that want it stub the token and opt in.
    monkeypatch.setattr(settings, "VERTEX_MEMORY_ENABLED", False)

    # Tracing opens a Cloud Trace exporter and a background export thread.
    # Tests that want spans use the memory_tracer fixture instead.
    monkeypatch.setattr(settings, "TRACING_ENABLED", False)

    # No Cloud Run client either. Guard tests must prove a refusal happens
    # before any network call, so constructing a real client would both slow
    # the suite and hide the very property under test.
    from app.cloud.runadmin import CloudRunAdmin
    from app.cloud.pricing import CloudRunPricing
    from app.cloud.usage import ServiceUsage

    monkeypatch.setattr(CloudRunAdmin, "_get_client", classmethod(lambda cls: None))
    # Same reasoning for the FinOps reads: the billing catalog is an HTTP call
    # and constructing a Monitoring client does credential discovery, both of
    # which put real network latency inside a suite that must not have any.
    monkeypatch.setattr(ServiceUsage, "_get_client", classmethod(lambda cls: None))
    CloudRunPricing.reset()
    ServiceUsage.reset()

    GeminiClient.reset()
    GemmaScreen.reset()
    VertexMemory.reset()
    Tracing.reset()
    FirestoreBackend.reset()
    ModelArmorShield.reset()
    yield
    Tracing.reset()
    VertexMemory.reset()
    GemmaScreen.reset()
    CloudRunPricing.reset()
    ServiceUsage.reset()
    GeminiClient.reset()
    FirestoreBackend.reset()
    ModelArmorShield.reset()
    CloudRunAdmin.reset()


@pytest.fixture(autouse=True)
def clean_stores():
    """Reset process-local state so tests cannot leak into each other."""
    from app.compiler.engine import ThorForjaEngine
    from app.compiler.recorder import TrajectoryRecorder
    from app.security.human_gate import HumanApprovalGate
    from app.storage.audit_ledger import AuditLedger
    from app.storage.memory_bank import MemoryBank

    from app.ingest.monitoring import DeliveryLedger

    for store in (AuditLedger, MemoryBank, HumanApprovalGate, TrajectoryRecorder,
                  ThorForjaEngine, DeliveryLedger):
        store.clear()
    yield


@pytest.fixture
def sample_incident_payload():
    return {
        "incident_id": "inc-9021",
        "service_id": "cloud-run/auth-service",
        "severity": "CRITICAL",
        "metric_name": "db_connection_pool_saturation",
        "error_message": "504 Gateway Timeout: DB connection pool exhausted (>98%)",
        "telemetry_data": {
            "active_connections": 98,
            "max_connections": 100,
            "p99_latency_ms": 4200,
        },
    }


@pytest.fixture
def memory_tracer(monkeypatch):
    """A real tracer whose spans land in memory instead of Cloud Trace.

    Wired by replacing the provider builder rather than by adding a test-only
    entry point to Tracing: the production configure() path, including its
    failure handling, is what runs here.
    """
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()

    def build(cls):
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        return provider

    monkeypatch.setattr(settings, "TRACING_ENABLED", True)
    monkeypatch.setattr(Tracing, "_build_provider", classmethod(build))
    Tracing.reset()
    Tracing.configure()
    yield exporter
    Tracing.reset()
