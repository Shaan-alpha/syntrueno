"""The Cloud Monitoring -> Pub/Sub -> swarm path.

This is the only entry point that reaches the swarm with no human in the loop,
so the tests that matter here are the ones about who may call it and what
happens when the same alert arrives twice. Nothing in this file touches the
network.
"""

import base64
import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.ingest.monitoring import (
    DeliveryLedger,
    PushAuthenticator,
    PushRejected,
    to_incident_alert,
)
from app.main import app
from app.models import IncidentSeverity

client = TestClient(app)

PUSH_SA = "syntrueno-pubsub-push@composed-maxim-498517-f0.iam.gserviceaccount.com"


def _envelope(incident: dict, message_id: str = "msg-1") -> dict:
    body = json.dumps({"incident": incident, "version": "1.2"}).encode()
    return {
        "message": {
            "data": base64.b64encode(body).decode(),
            "messageId": message_id,
        },
        "subscription": "projects/p/subscriptions/syntrueno-alerts",
    }


OPEN_INCIDENT = {
    "incident_id": "0.abc123",
    "state": "open",
    "summary": "Memory utilization above 90% for syntrueno-canary",
    "policy_name": "canary-memory",
    "condition_name": "memory > 90%",
    "resource": {"type": "cloud_run_revision",
                 "labels": {"service_name": "syntrueno-canary"}},
    "metric": {"type": "run.googleapis.com/container/memory/utilizations"},
}


@pytest.fixture
def _authenticated(monkeypatch):
    """Open the gate with a verified caller, without doing crypto."""
    monkeypatch.setattr(settings, "PUBSUB_INGEST_ENABLED", True)
    monkeypatch.setattr(settings, "PUBSUB_PUSH_SERVICE_ACCOUNT", PUSH_SA)
    monkeypatch.setattr(PushAuthenticator, "verify",
                        staticmethod(lambda auth: PUSH_SA))


# ------------------------------------------------------------------- authn

def test_ingest_is_closed_by_default():
    """Deploying without configuring the caller must not open the path."""
    response = client.post("/api/v1/ingest/pubsub", json=_envelope(OPEN_INCIDENT))
    assert response.status_code == 401


def test_a_missing_token_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "PUBSUB_INGEST_ENABLED", True)
    monkeypatch.setattr(settings, "PUBSUB_PUSH_SERVICE_ACCOUNT", PUSH_SA)

    response = client.post("/api/v1/ingest/pubsub", json=_envelope(OPEN_INCIDENT))

    assert response.status_code == 401
    # The reason is audited, not returned -- it would be free reconnaissance.
    assert response.json()["detail"] == "unauthorized"


def test_an_unconfigured_service_account_fails_closed(monkeypatch):
    """An empty expectation would accept any Google-issued token on earth."""
    monkeypatch.setattr(settings, "PUBSUB_INGEST_ENABLED", True)
    monkeypatch.setattr(settings, "PUBSUB_PUSH_SERVICE_ACCOUNT", "")

    with pytest.raises(PushRejected) as exc:
        PushAuthenticator.verify("Bearer whatever")

    assert "no_expected_service_account" in str(exc.value)


def test_disabled_ingest_refuses_before_verifying_anything(monkeypatch):
    monkeypatch.setattr(settings, "PUBSUB_INGEST_ENABLED", False)

    with pytest.raises(PushRejected) as exc:
        PushAuthenticator.verify("Bearer anything")

    assert "disabled" in str(exc.value)


# -------------------------------------------------------------- delivery

def test_a_redelivered_message_does_not_re_run_the_swarm(_authenticated, monkeypatch):
    """Pub/Sub is at-least-once, and Monitoring re-notifies while open.

    Without this, one incident is remediated once per redelivery.
    """
    runs = []
    from app.agents import commander

    monkeypatch.setattr(commander.SyntruenoCommander, "process_incident",
                        classmethod(lambda cls, alert, **kw: runs.append(alert) or {}))

    envelope = _envelope(OPEN_INCIDENT, message_id="msg-repeat")
    first = client.post("/api/v1/ingest/pubsub", json=envelope)
    second = client.post("/api/v1/ingest/pubsub", json=envelope)

    assert first.status_code == 200
    assert second.json()["status"] == "DUPLICATE_IGNORED"
    assert len(runs) == 1


def test_a_closed_incident_is_acked_without_remediating(_authenticated, monkeypatch):
    """Remediating a recovered incident is damage for no reason."""
    runs = []
    from app.agents import commander

    monkeypatch.setattr(commander.SyntruenoCommander, "process_incident",
                        classmethod(lambda cls, alert, **kw: runs.append(alert) or {}))

    closed = {**OPEN_INCIDENT, "state": "closed"}
    response = client.post("/api/v1/ingest/pubsub", json=_envelope(closed))

    assert response.status_code == 200          # 200 = ack; a nack would retry
    assert response.json()["status"] == "NOT_ACTIONABLE"
    assert runs == []


def test_an_undecodable_body_is_acked_not_retried_forever(_authenticated):
    """A non-2xx here nacks, and Pub/Sub redelivers a body that will never parse."""
    response = client.post("/api/v1/ingest/pubsub", json={
        "message": {"data": "not-valid-base64!!!", "messageId": "msg-bad"},
        "subscription": "projects/p/subscriptions/s",
    })

    assert response.status_code == 200
    assert response.json()["status"] == "NOT_ACTIONABLE"


# ------------------------------------------------------------- translation

def test_monitoring_payload_becomes_an_incident_alert():
    alert = to_incident_alert({"incident": OPEN_INCIDENT})

    assert alert is not None
    assert alert.incident_id == "0.abc123"
    assert alert.service_id == "cloud_run_revision/syntrueno-canary"
    assert alert.metric_name.endswith("memory/utilizations")
    assert alert.telemetry_data["source"] == "cloud_monitoring"


def test_an_unknown_severity_becomes_high_not_low():
    """An unparsed severity is missing information. Guessing 'harmless' is
    the wrong way to be wrong."""
    alert = to_incident_alert(
        {"incident": {**OPEN_INCIDENT, "severity": "moderately-spicy"}})

    assert alert.severity == IncidentSeverity.HIGH


def test_a_body_with_no_incident_is_not_actionable():
    assert to_incident_alert({"version": "1.2"}) is None
    assert to_incident_alert({}) is None


# --------------------------------------------------------------- autonomy

def test_the_event_path_does_not_confer_approval(_authenticated):
    """Automating triage must not widen the action space.

    A consequential action arriving with no human in the loop still stops at
    the human gate -- otherwise the event path is a way around it.
    """
    response = client.post("/api/v1/ingest/pubsub", json=_envelope(OPEN_INCIDENT))
    body = response.json()

    assert response.status_code == 200
    assert body.get("execution_status") != "APPLIED"
    assert body["ingest"]["verified_caller"] == PUSH_SA


def test_the_delivery_ledger_stays_bounded():
    """A long-lived container must not accumulate every id it has ever seen."""
    DeliveryLedger.clear()
    for i in range(DeliveryLedger.MAX_TRACKED + 200):
        DeliveryLedger.is_duplicate(f"msg-{i}")

    assert len(DeliveryLedger._seen) <= DeliveryLedger.MAX_TRACKED
    # The most recent ids are the ones worth keeping: those are what Pub/Sub
    # would still be retrying.
    assert DeliveryLedger.is_duplicate(f"msg-{DeliveryLedger.MAX_TRACKED + 199}")
