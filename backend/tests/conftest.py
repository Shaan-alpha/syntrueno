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
    FirestoreBackend.reset()
    ModelArmorShield.reset()
    yield
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
