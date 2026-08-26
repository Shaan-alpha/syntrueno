import json
import logging
import os
from typing import Any, Dict

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logger = logging.getLogger(__name__)


def _sse(payload: Dict[str, Any]) -> str:
    """Encode one server-sent event."""
    return f"data: {json.dumps(payload, default=str)}\n\n"

from app.config import settings
from app.models import (
    AgentRole,
    AuditLogEntry,
    IncidentAlert,
    ModelArmorScanRequest,
    ModelArmorScanResult,
)
from app.cloud.runadmin import CloudRunAdmin
from app.security.model_armor import ModelArmorShield
from app.security.human_gate import (
    HumanApprovalGate,
    ApprovalNotFound,
    ApprovalStateError,
)
from app.ingest.monitoring import (
    DeliveryLedger,
    PubSubPushEnvelope,
    PushAuthenticator,
    PushRejected,
    to_incident_alert,
)
from app.registry.a2a import AgentRegistry
from app.registry.agent_card import registry_service_id, to_a2a_agent_card
from app.agents.commander import SyntruenoCommander
from app.agents.finops import FinOpsAgent
from app.storage.audit_ledger import AuditLedger
from app.telemetry.tracing import Tracing
from app.storage.firestore_backend import FirestoreBackend
from app.storage.memory_bank import MemoryBank
from app.compiler.recorder import TrajectoryRecorder
from app.compiler.engine import ThorForjaEngine
from app.llm.gemini import GeminiClient

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=(
        "Zero-trust autonomous cloud operations swarm. Gemini-backed agents, "
        "guarded Cloud Run remediation, and a hash-chained audit ledger."
    ),
)

# Start the exporter once, at import, rather than lazily on the first incident.
# The batch processor needs a background thread and Cloud Trace needs
# credentials; discovering a problem with either during a judge's first request
# is worse than discovering it in the startup logs. configure() cannot raise, so
# a failure here degrades to untraced rather than to a service that will not boot.
Tracing.configure()


# Origin allowlist. Previously "*" with credentials enabled, which let any
# website make credentialed cross-origin calls to the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


# --- 1. Health & status -----------------------------------------------------
# Note: /healthz is NOT used. Google Frontend intercepts that path on Cloud Run
# and returns its own 404 before the request reaches this container.

@app.get("/api/v1/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "llm_available": GeminiClient.is_available(),
    }


@app.get("/api/v1/status")
def system_status() -> Dict[str, Any]:
    return {
        "project": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "model_armor_active": settings.MODEL_ARMOR_ENABLED,
        "registered_agents_count": len(AgentRegistry.list_all_cards()),
        "compiled_skills_count": len(ThorForjaEngine.list_compiled_skills()),
        "audit_ledger_size": len(AuditLedger.get_all_entries()),
        # Signable, not merely stored. Every demo run leaves a TIER_3 approval
        # behind and each dies 30 minutes later, so counting dead records made
        # the console advertise 13 approvals awaiting a signature that nothing
        # could act on -- a number that only climbs across a month of judging.
        "pending_approvals": sum(
            1 for r in HumanApprovalGate.list_all()
            if r.status == "PENDING" and not HumanApprovalGate.is_expired(r)
        ),
        "llm": {
            "available": GeminiClient.is_available(),
            "fast_model": settings.FAST_MODEL,
            "reasoning_model": settings.REASONING_MODEL,
            "simulation_mode": settings.SIMULATION_MODE,
        },
        "remediation": {
            "dry_run": settings.REMEDIATION_DRY_RUN,
            "allowlisted_service": settings.CANARY_SERVICE_NAME,
        },
        # Reported rather than assumed: if the store is in-memory, the service
        # says so instead of claiming durability it does not have.
        "persistence": {
            "firestore": FirestoreBackend.status(),
            "audit_ledger": AuditLedger.status(),
            "memory_bank": MemoryBank.status(),
            "tracing": Tracing.status(),
            "trajectories": TrajectoryRecorder.status(),
        },
    }


# --- 2. A2A protocol --------------------------------------------------------

def _public_base_url(request: Request) -> str:
    """The origin a client outside this container should call.

    Cloud Run terminates TLS at its proxy and forwards plain HTTP, so
    ``request.base_url`` reports ``http://`` on a service only reachable over
    ``https://``. Publishing that in a discovery document points every A2A
    client at the wrong scheme, and a discovery document is exactly the place
    that error propagates from. The proxy tells us the real scheme in
    ``X-Forwarded-Proto``; trust it over the socket.
    """
    base = str(request.base_url)
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    if forwarded in ("http", "https"):
        scheme, _, rest = base.partition("://")
        if scheme != forwarded:
            return f"{forwarded}://{rest}"
    return base


@app.get("/.well-known/agent-card.json")
def get_master_agent_card(request: Request) -> Dict[str, Any]:
    """The A2A discovery document.

    This path is reserved by the A2A specification, so serving it is a claim
    that what comes back matches the A2A schema. It is rendered through an
    adapter rather than dumped from the internal model, which uses different
    field names and omits several required ones.
    """
    card = AgentRegistry.get_agent_card(AgentRole.COMMANDER)
    if not card:
        raise HTTPException(status_code=404, detail="Master agent card not found")
    return to_a2a_agent_card(card, _public_base_url(request))


@app.get("/a2a/v1/registry")
def list_agent_registry() -> Dict[str, Any]:
    cards = AgentRegistry.list_all_cards()
    return {
        "agents": [c.model_dump() for c in cards],
        # Where these same agents are published for cross-department discovery.
        # This local registry stays the dispatch source of truth -- it is what
        # the Commander resolves against and what mints capability tokens. The
        # upstream one is the catalogue: a client that has never heard of this
        # deployment can find these agents there.
        #
        # Reported rather than asserted in prose, and derived from the same
        # helper scripts/register_agents.py uses, so this cannot drift into
        # naming entries that were never created.
        "upstream_registry": {
            "provider": "Google Agent Registry",
            "location": settings.AGENT_ENGINE_LOCATION,
            "services": [
                f"projects/{settings.GOOGLE_CLOUD_PROJECT}/locations/"
                f"{settings.AGENT_ENGINE_LOCATION}/services/"
                f"{registry_service_id(c.name)}"
                for c in cards
            ],
        },
    }


# --- 3. Model Armor adversarial studio --------------------------------------

@app.post("/api/v1/security/model-armor/scan", response_model=ModelArmorScanResult)
def scan_prompt(req: ModelArmorScanRequest) -> ModelArmorScanResult:
    """Screens a human-typed prompt. Used by the adversarial studio."""
    return ModelArmorShield.screen_inbound(req.prompt, user_role=req.user_identity)


# --- 4. Swarm operations ----------------------------------------------------

@app.post("/api/v1/swarm/incident/triage")
def triage_incident(alert: IncidentAlert) -> Dict[str, Any]:
    """Run the swarm against an incident.

    Inbound telemetry is neutralised rather than refused. A quoted command in a
    log excerpt is evidence about the incident, not an attack on the agent, and
    rejecting the alert would break the product's primary use case.
    """
    # One span over the whole request, so screening and the swarm land in the
    # same trace. Screening is instrumented here rather than inside
    # ModelArmorShield because the shield is also called from the adversarial
    # studio, where there is no incident to attach it to.
    with Tracing.span("triage", incident_id=alert.incident_id):
        with Tracing.span("screen") as screen_span:
            armor = ModelArmorShield.neutralize_inbound(alert.error_message)
            Tracing.annotate(
                screen_span,
                verdict=armor.verdict,
                layers=",".join(armor.screened_by),
                threats=len(armor.detected_threats),
                latency_ms=armor.latency_ms,
                degraded_reason=armor.degraded_reason,
            )
        alert.error_message = armor.sanitized_prompt

        result = SyntruenoCommander.process_incident(alert)
        result["model_armor"] = armor.model_dump()

        TrajectoryRecorder.record_from_result(alert.metric_name, result)

    # Outside the span, so the spans being pushed are complete ones. Cloud Run
    # throttles CPU between requests, so the batch processor's background thread
    # never runs once the response is sent -- without this the spans queue and
    # are silently dropped, which is exactly what happened on the first deploy:
    # /api/v1/status reported tracing active while the project held zero traces.
    Tracing.flush()
    return result


@app.post("/api/v1/ingest/pubsub")
def ingest_monitoring_alert(
    envelope: PubSubPushEnvelope,
    authorization: str = Header(default=""),
) -> Dict[str, Any]:
    """Cloud Monitoring alert, delivered by Pub/Sub push. No human involved.

    The status codes matter as much as the logic, because Pub/Sub reads them:
    a non-2xx is a nack and the message comes back. So this returns 200 for
    everything it has deliberately decided not to act on -- a closed incident,
    a redelivery, an unparseable body -- and reserves 401 for a caller it could
    not authenticate, which is the one case where retrying is pointless and
    being noisy is correct.

    Automating triage does not widen what the swarm may do. A Tier 3 action
    that arrives here still stops at the human gate.
    """
    try:
        caller = PushAuthenticator.verify(authorization)
    except PushRejected as exc:
        # The reason is audited, never returned: telling an unauthenticated
        # caller *why* they failed is free reconnaissance.
        logger.warning("Rejected Pub/Sub push: %s", exc)
        raise HTTPException(status_code=401, detail="unauthorized")

    message_id = envelope.message.id
    if DeliveryLedger.is_duplicate(message_id):
        # At-least-once delivery. Re-running the swarm would re-remediate a
        # single incident once per redelivery.
        return {"status": "DUPLICATE_IGNORED", "message_id": message_id}

    alert = to_incident_alert(envelope.message.decoded())
    if alert is None:
        return {"status": "NOT_ACTIONABLE", "message_id": message_id}

    armor = ModelArmorShield.neutralize_inbound(alert.error_message)
    alert.error_message = armor.sanitized_prompt

    result = SyntruenoCommander.process_incident(alert)
    result["model_armor"] = armor.model_dump()
    result["ingest"] = {
        "source": "cloud_monitoring",
        "message_id": message_id,
        "verified_caller": caller,
        "subscription": envelope.subscription,
    }

    TrajectoryRecorder.record_from_result(alert.metric_name, result)
    return result


@app.post("/api/v1/swarm/incident/stream")
def stream_incident(alert: IncidentAlert) -> StreamingResponse:
    """Same work as /triage, but each stage is pushed as it completes.

    A real incident spends 15-25 seconds inside model calls. Without this the
    console can only spin, or invent progress it has no basis for. Streaming
    lets it show the actual stage, the actual model, and the actual elapsed
    time for each step.
    """
    armor = ModelArmorShield.neutralize_inbound(alert.error_message)
    alert.error_message = armor.sanitized_prompt

    def events():
        # The screening already happened; report it as the first stage so the
        # console can show the threat count before the slow work begins.
        yield _sse({
            "type": "stage", "stage": "armor", "state": "done",
            "duration_ms": armor.latency_ms,
            "threats": armor.detected_threats,
            "redactions": armor.redacted_pii,
            # Which layers actually returned a verdict, and what stopped any
            # that did not. Without these the console can show that something
            # was caught but not that three independent layers looked, nor
            # that one of them was unavailable when it mattered.
            "screened_by": armor.screened_by,
            "degraded_reason": armor.degraded_reason,
            "detail": (
                f"{len(armor.detected_threats)} injection attempt(s) neutralised"
                if armor.detected_threats else "No threats detected"
            ),
        })

        final = None
        try:
            for event in SyntruenoCommander.run(alert):
                if event.get("type") == "result":
                    final = event["result"]
                yield _sse(event)
        except Exception as exc:  # noqa: BLE001 - the client must hear about it
            logger.exception("Incident stream failed")
            yield _sse({
                "type": "error",
                "message": f"{type(exc).__name__}: {str(exc)[:200]}",
            })
            return

        if final is not None:
            TrajectoryRecorder.record_from_result(alert.metric_name, final)
        yield _sse({"type": "done"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Cloud Run sits behind a proxy that will otherwise buffer the
            # whole response and defeat the point of streaming.
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/v1/swarm/finops/audit")
def run_finops_audit() -> Dict[str, Any]:
    return FinOpsAgent.audit_spending_and_waste()


# --- 5. Governance ----------------------------------------------------------

class SignApprovalRequest(BaseModel):
    """Only identifies which approval to sign and who is signing.

    The action being approved is read from the server's stored record. There is
    deliberately no field here for the caller to supply one.
    """

    approval_id: str
    engineer_id: str


@app.get("/api/v1/governance/approvals")
def list_approvals() -> Dict[str, Any]:
    return {"approvals": [r.model_dump() for r in HumanApprovalGate.list_all()]}


@app.post("/api/v1/governance/approvals/sign")
def sign_approval(req: SignApprovalRequest) -> Dict[str, Any]:
    try:
        record = HumanApprovalGate.sign_approval(req.approval_id, req.engineer_id)
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ApprovalStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "SUCCESS", "approval_record": record.model_dump()}


@app.post("/api/v1/governance/approvals/reject")
def reject_approval(req: SignApprovalRequest) -> Dict[str, Any]:
    try:
        record = HumanApprovalGate.reject_approval(req.approval_id, req.engineer_id)
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "REJECTED", "approval_record": record.model_dump()}


class ExecuteRemediationRequest(BaseModel):
    approval_id: str


@app.post("/api/v1/swarm/remediation/execute")
def execute_remediation(req: ExecuteRemediationRequest) -> Dict[str, Any]:
    """Execute the action a signed approval authorises.

    The action comes from the server's stored approval, never from the caller.
    Every guard in CloudRunAdmin still runs, so a signature is necessary but
    not sufficient: the service allowlist, verb allowlist, and destructive
    screen all apply again at execution time.
    """
    record = HumanApprovalGate.get(req.approval_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No approval {req.approval_id!r}")
    if record.status != "APPROVED":
        raise HTTPException(
            status_code=409,
            detail=f"Approval {req.approval_id!r} is {record.status}, not APPROVED.",
        )
    if record.consumed_at is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Approval {req.approval_id!r} was already spent at "
                f"{record.consumed_at}. Each execution requires its own signature."
            ),
        )

    result = CloudRunAdmin.apply(record.requested_action, approval_id=req.approval_id)

    AuditLedger.record_entry(
        AuditLogEntry(
            event_id=f"exec-{req.approval_id[-8:]}",
            session_id=record.incident_id,
            agent_name="CloudRunAdmin",
            action_name=record.requested_action.tool_name,
            status=result["status"],
            details={
                "approval_id": req.approval_id,
                "verified": result.get("verified"),
                "before": result.get("before", {}).get("memory"),
                "after": result.get("after", {}).get("memory"),
            },
            duration_ms=result.get("duration_ms", 0.0),
        )
    )
    return result


@app.get("/api/v1/cloud/canary")
def describe_canary() -> Dict[str, Any]:
    """Live configuration of the one service the swarm may mutate."""
    return CloudRunAdmin.describe()


@app.get("/api/v1/governance/audit-ledger")
def get_audit_ledger() -> Dict[str, Any]:
    return {
        "ledger_entries": AuditLedger.get_all_entries(),
        "is_chain_valid": AuditLedger.verify_integrity(),
    }


# --- 6. ThorForja compiler --------------------------------------------------

@app.post("/api/v1/compiler/mine")
def mine_trajectories() -> Dict[str, Any]:
    compiled = ThorForjaEngine.mine_and_compile()
    return {
        "newly_compiled_count": len(compiled),
        "all_compiled_skills": [c.model_dump() for c in ThorForjaEngine.list_compiled_skills()],
    }


class ExecuteCompiledSkillRequest(BaseModel):
    skeleton_signature: str
    inputs: Dict[str, Any]


@app.post("/api/v1/compiler/execute")
def execute_compiled_skill(req: ExecuteCompiledSkillRequest) -> Dict[str, Any]:
    """Derive a compiled skill's action without calling a model.

    Named ``/execute`` for compatibility, but it proposes rather than executes.
    The action it returns still has to go through the Judge and, at Tier 3, the
    human gate -- a skill that could act on its own would be a way around every
    guard in the system, unlocked by getting a sequence to repeat.
    """
    result = ThorForjaEngine.propose(req.skeleton_signature, req.inputs)
    if result is None:
        raise HTTPException(status_code=404, detail="No compiled skill for that signature")
    return result


@app.get("/api/v1/compiler/trajectories")
def list_trajectories() -> Dict[str, Any]:
    return {"trajectories": TrajectoryRecorder.get_all_trajectories()}


# --- 7. Static SPA ----------------------------------------------------------

_static = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if not os.path.exists(_static):
    _dist = os.path.abspath(
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "frontend", "dist",
        )
    )
    if os.path.exists(_dist):
        _static = _dist

if os.path.exists(_static):
    app.mount("/", StaticFiles(directory=_static, html=True), name="static")
