"""Cloud Monitoring alert -> Pub/Sub push -> the swarm.

This is the only entry point where an incident reaches the swarm with no human
in the loop, which makes it the most dangerous surface in the system. Three
properties hold it shut:

1. **The caller is authenticated, not merely expected.** The service is
   deployed ``--allow-unauthenticated`` because the console has to be reachable
   from a browser, so Cloud Run will not check the caller for us. A push
   subscription configured with an OIDC token therefore has to be verified
   *here* -- issuer, audience, and the exact service account. Anyone can POST
   to this path; only Pub/Sub can get past this function.

2. **Redelivery is not re-remediation.** Pub/Sub is at-least-once, and Cloud
   Monitoring re-notifies while an incident stays open. Without a dedupe the
   same alert re-runs the swarm on every redelivery, which at Tier 2 means
   repeatedly mutating live infrastructure over one incident.

3. **Autonomy stops where consequence starts.** This path automates *triage* --
   diagnosis and judgement. It does not widen the action space and it does not
   confer approval: a Tier 3 action arriving through here still stops at the
   human gate exactly as it does through the console.

The alert body is untrusted input from outside the trust boundary, and it is
screened by Model Armor on the triage path like any other inbound telemetry.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import threading
from collections import OrderedDict
from typing import Any, Dict, Optional

from pydantic import BaseModel

from app.config import settings
from app.models import IncidentAlert, IncidentSeverity

logger = logging.getLogger(__name__)

# Google's OIDC issuers for service-account identity tokens.
_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


class PushRejected(Exception):
    """The push could not be trusted. Never leaks why to the caller."""


class PubSubMessage(BaseModel):
    data: Optional[str] = None
    message_id: Optional[str] = None
    messageId: Optional[str] = None  # Pub/Sub sends camelCase
    publish_time: Optional[str] = None
    publishTime: Optional[str] = None
    attributes: Dict[str, str] = {}

    @property
    def id(self) -> str:
        return self.message_id or self.messageId or ""

    def decoded(self) -> Dict[str, Any]:
        """The Monitoring notification carried in ``data``.

        Returns ``{}`` rather than raising: a malformed body is a fact to audit,
        not a reason to 500 back at Pub/Sub and trigger endless redelivery.
        """
        if not self.data:
            return {}
        try:
            raw = base64.b64decode(self.data)
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
            logger.warning("Undecodable Pub/Sub payload: %s", exc)
            return {}


class PubSubPushEnvelope(BaseModel):
    message: PubSubMessage
    subscription: str = ""


class PushAuthenticator:
    """Verifies the OIDC token Pub/Sub attaches to a push request."""

    @staticmethod
    def verify(authorization: Optional[str]) -> str:
        """Return the verified caller email, or raise :class:`PushRejected`.

        Fails closed on every path. An unverifiable token is indistinguishable
        from a forged one, so both are refused.
        """
        if not settings.PUBSUB_INGEST_ENABLED:
            raise PushRejected("pubsub_ingest_disabled")

        # Checked before any token work. An empty expectation would accept any
        # Google-issued OIDC token, which is every Google account on earth, so
        # this is a misconfiguration no request can be valid under -- there is
        # nothing to gain by verifying a signature first.
        expected = settings.PUBSUB_PUSH_SERVICE_ACCOUNT
        if not expected:
            raise PushRejected("no_expected_service_account_configured")

        if not authorization or not authorization.startswith("Bearer "):
            raise PushRejected("missing_bearer_token")

        token = authorization.split(" ", 1)[1].strip()
        if not token:
            raise PushRejected("empty_bearer_token")

        try:
            from google.auth.transport import requests as ga_requests
            from google.oauth2 import id_token

            claims = id_token.verify_oauth2_token(
                token,
                ga_requests.Request(),
                audience=settings.PUBSUB_AUDIENCE or None,
            )
        except Exception as exc:
            logger.warning("Push token rejected: %s", str(exc)[:160])
            raise PushRejected("token_verification_failed") from exc

        if claims.get("iss") not in _ISSUERS:
            raise PushRejected("untrusted_issuer")

        email = claims.get("email", "")
        if email != expected:
            raise PushRejected("unexpected_service_account")
        if not claims.get("email_verified", False):
            raise PushRejected("unverified_email_claim")

        return email


class DeliveryLedger:
    """Remembers which Pub/Sub messages have already been acted on.

    Bounded on purpose: this guards a long-lived container, and an unbounded
    set of every message id ever seen is a slow memory leak. Evicting oldest
    first is safe because redelivery is prompt -- a message old enough to fall
    out of this window is not one Pub/Sub is still retrying.
    """

    _seen: "OrderedDict[str, None]" = OrderedDict()
    _lock = threading.Lock()
    MAX_TRACKED = 2048

    @classmethod
    def is_duplicate(cls, message_id: str) -> bool:
        """True when this id was seen before. Records it either way."""
        if not message_id:
            # No id means no way to dedupe. Treat as fresh and let the
            # incident-level guards handle it.
            return False
        with cls._lock:
            if message_id in cls._seen:
                cls._seen.move_to_end(message_id)
                return True
            cls._seen[message_id] = None
            while len(cls._seen) > cls.MAX_TRACKED:
                cls._seen.popitem(last=False)
            return False

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._seen.clear()


# Monitoring reports severity as free text when it reports it at all. Anything
# unrecognised becomes HIGH rather than LOW: an unparsed severity is missing
# information, and guessing "harmless" is the wrong way to be wrong.
_SEVERITY_BY_NAME = {
    "critical": IncidentSeverity.CRITICAL,
    "error": IncidentSeverity.HIGH,
    "high": IncidentSeverity.HIGH,
    "warning": IncidentSeverity.MEDIUM,
    "medium": IncidentSeverity.MEDIUM,
    "info": IncidentSeverity.LOW,
    "low": IncidentSeverity.LOW,
}


def to_incident_alert(payload: Dict[str, Any]) -> Optional[IncidentAlert]:
    """Translate a Cloud Monitoring notification into an ``IncidentAlert``.

    Returns ``None`` when the notification is not something to act on -- a
    closed incident, or a body with no incident in it. Returning None is a
    successful outcome here: it means Pub/Sub gets its ack and nothing runs.
    """
    incident = payload.get("incident")
    if not isinstance(incident, dict):
        return None

    # A closing notification means the condition recovered. Remediating a
    # resolved incident is how an autonomous system does damage for no reason.
    if str(incident.get("state", "open")).lower() == "closed":
        return None

    resource = incident.get("resource", {}) or {}
    labels = resource.get("labels", {}) or {}
    metric = incident.get("metric", {}) or {}

    service = (
        labels.get("service_name")
        or labels.get("revision_name")
        or incident.get("resource_display_name")
        or "unknown-service"
    )
    resource_type = resource.get("type", "cloud_run_revision")

    summary = (
        incident.get("summary")
        or incident.get("documentation", {}).get("content")
        or incident.get("condition_name")
        or "Cloud Monitoring alert with no summary"
    )

    severity = _SEVERITY_BY_NAME.get(
        str(incident.get("severity", "")).lower(), IncidentSeverity.HIGH
    )

    return IncidentAlert(
        incident_id=str(incident.get("incident_id") or "monitoring-unknown"),
        service_id=f"{resource_type}/{service}",
        severity=severity,
        metric_name=str(
            metric.get("type") or metric.get("displayName") or "unknown_metric"
        ),
        error_message=str(summary),
        telemetry_data={
            "source": "cloud_monitoring",
            "policy_name": incident.get("policy_name"),
            "condition_name": incident.get("condition_name"),
            "started_at": incident.get("started_at"),
            "url": incident.get("url"),
            "resource_labels": labels,
        },
    )
