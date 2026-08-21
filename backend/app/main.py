import os
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import settings
from app.models import AgentRole, IncidentAlert, ModelArmorScanRequest, ModelArmorScanResult
from app.security.model_armor import ModelArmorShield
from app.security.human_gate import (
    HumanApprovalGate,
    ApprovalNotFound,
    ApprovalStateError,
)
from app.registry.a2a import AgentRegistry
from app.agents.commander import SentinelCommander
from app.agents.finops import FinOpsAgent
from app.storage.audit_ledger import AuditLedger
from app.compiler.recorder import TrajectoryRecorder
from app.compiler.engine import CompyleEngine
from app.llm.gemini import GeminiClient

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=(
        "Zero-trust autonomous cloud operations swarm. Gemini-backed agents, "
        "guarded Cloud Run remediation, and a hash-chained audit ledger."
    ),
)

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
        "compiled_skills_count": len(CompyleEngine.list_compiled_skills()),
        "audit_ledger_size": len(AuditLedger.get_all_entries()),
        "pending_approvals": sum(
            1 for r in HumanApprovalGate.list_all() if r.status == "PENDING"
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
    }


# --- 2. A2A protocol --------------------------------------------------------

@app.get("/.well-known/agent-card.json")
def get_master_agent_card() -> Dict[str, Any]:
    card = AgentRegistry.get_agent_card(AgentRole.COMMANDER)
    if not card:
        raise HTTPException(status_code=404, detail="Master agent card not found")
    return card.model_dump()


@app.get("/a2a/v1/registry")
def list_agent_registry() -> Dict[str, Any]:
    return {"agents": [c.model_dump() for c in AgentRegistry.list_all_cards()]}


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
    armor = ModelArmorShield.neutralize_inbound(alert.error_message)
    alert.error_message = armor.sanitized_prompt

    result = SentinelCommander.process_incident(alert)
    result["model_armor"] = armor.model_dump()

    TrajectoryRecorder.record_trajectory(
        incident_type=alert.metric_name,
        tool_sequence=result.get("executed_tools", []),
        parameters=result.get("proposed_action", {}).get("parameters", {}),
        duration_ms=result.get("total_duration_ms", 0.0),
    )
    return result


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


@app.get("/api/v1/governance/audit-ledger")
def get_audit_ledger() -> Dict[str, Any]:
    return {
        "ledger_entries": AuditLedger.get_all_entries(),
        "is_chain_valid": AuditLedger.verify_integrity(),
    }


# --- 6. ThorForja compiler --------------------------------------------------

@app.post("/api/v1/compiler/mine")
def mine_trajectories() -> Dict[str, Any]:
    compiled = CompyleEngine.mine_and_compile()
    return {
        "newly_compiled_count": len(compiled),
        "all_compiled_skills": [c.model_dump() for c in CompyleEngine.list_compiled_skills()],
    }


class ExecuteCompiledSkillRequest(BaseModel):
    skeleton_signature: str
    inputs: Dict[str, Any]


@app.post("/api/v1/compiler/execute")
def execute_compiled_skill(req: ExecuteCompiledSkillRequest) -> Dict[str, Any]:
    result = CompyleEngine.execute_compiled_skill(req.skeleton_signature, req.inputs)
    if not result:
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
