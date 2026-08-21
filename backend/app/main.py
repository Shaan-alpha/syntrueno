import os
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import Dict, Any, List, Optional

from app.config import settings
from app.models import (
    AgentRole,
    IncidentAlert,
    ModelArmorScanRequest,
    ModelArmorScanResult,
    ApprovalRecord,
)
from app.security.model_armor import ModelArmorShield
from app.registry.a2a import AgentRegistry
from app.agents.commander import SentinelCommander
from app.agents.finops import FinOpsAgent
from app.security.human_gate import HumanApprovalGate
from app.storage.audit_ledger import AuditLedger
from app.compiler.recorder import TrajectoryRecorder
from app.compiler.engine import CompyleEngine

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Syntrueno - Zero-Trust Autonomous Cloud Operations Swarm with ThorForja Self-Compiling Engine and Model Armor.",
)

# Enable CORS for Next.js / Vite UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 1. Health & Status ---
@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": settings.PROJECT_NAME, "version": settings.VERSION}

@app.get("/api/v1/status")
def system_status():
    return {
        "project": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "model_armor_active": settings.MODEL_ARMOR_ENABLED,
        "registered_agents_count": len(AgentRegistry.list_all_cards()),
        "compiled_skills_count": len(CompyleEngine.list_compiled_skills()),
        "audit_ledger_size": len(AuditLedger.get_all_entries()),
    }

# --- 2. Open A2A Protocol Endpoints ---
@app.get("/.well-known/agent-card.json")
def get_master_agent_card():
    """A2A Standard Discovery Card for SentinelMesh master fleet."""
    commander_card = AgentRegistry.get_agent_card(AgentRole.COMMANDER)
    if not commander_card:
        raise HTTPException(status_code=404, detail="Master agent card not found")
    return commander_card.model_dump()

@app.get("/a2a/v1/registry")
def list_agent_registry():
    return {"agents": [card.model_dump() for card in AgentRegistry.list_all_cards()]}

# --- 3. Google Cloud Model Armor & Adversarial Playground ---
@app.post("/api/v1/security/model-armor/scan", response_model=ModelArmorScanResult)
def scan_prompt_with_model_armor(req: ModelArmorScanRequest):
    return ModelArmorShield.sanitize_prompt(req.prompt, user_role=req.user_identity)

# --- 4. Swarm Operations & Triage ---
@app.post("/api/v1/swarm/incident/triage")
def triage_incident(alert: IncidentAlert):
    # 1. Inspect incident error message with Model Armor
    armor_scan = ModelArmorShield.sanitize_prompt(alert.error_message)
    if not armor_scan.is_safe:
        raise HTTPException(status_code=400, detail=f"Model Armor quarantined alert: {armor_scan.detected_threats}")

    # 2. Record trajectory for Compyle engine
    tool_seq = ["diagnose_pool", "scale_cloud_sql", "verify_sandbox"]
    TrajectoryRecorder.record_trajectory(alert.metric_name, tool_seq, alert.telemetry_data, 1200.0)

    # 3. Coordinate Swarm Triage
    return SentinelCommander.process_incident(alert)

@app.get("/api/v1/swarm/finops/audit")
def run_finops_audit():
    return FinOpsAgent.audit_spending_and_waste()

# --- 5. Governance & Human-in-the-Loop ---
class SignApprovalRequest(BaseModel):
    engineer_id: str
    approval_record: ApprovalRecord

@app.post("/api/v1/governance/approvals/sign")
def sign_approval(req: SignApprovalRequest):
    try:
        signed_record = HumanApprovalGate.sign_approval(req.approval_record, req.engineer_id)
        return {"status": "SUCCESS", "approval_record": signed_record.model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/v1/governance/audit-ledger")
def get_audit_ledger():
    return {
        "ledger_entries": AuditLedger.get_all_entries(),
        "is_chain_valid": AuditLedger.verify_integrity(),
    }

# --- 6. Compyle Self-Compilation Engine ---
@app.post("/api/v1/compiler/mine")
def mine_trajectories_and_compile():
    compiled = CompyleEngine.mine_and_compile(min_occurrences=1)
    return {
        "newly_compiled_count": len(compiled),
        "all_compiled_skills": [c.model_dump() for c in CompyleEngine.list_compiled_skills()],
    }

class ExecuteCompiledSkillRequest(BaseModel):
    skeleton_signature: str
    inputs: Dict[str, Any]

@app.post("/api/v1/compiler/execute")
def execute_compiled_skill(req: ExecuteCompiledSkillRequest):
    result = CompyleEngine.execute_compiled_skill(req.skeleton_signature, req.inputs)
    if not result:
        raise HTTPException(status_code=404, detail="No matching compiled skill found for signature")
    return result

# --- 7. Keynote Replay Stream (Deterministic Fail-Safe) ---
@app.get("/api/v1/replay/keynote-stream")
def get_keynote_replay_stream():
    """Provides deterministic NDJSON replay stream for zero-flakiness demo recordings."""
    return {
        "simulation_mode": True,
        "recorded_ticks": [
            {"tick": 1, "agent": "ModelArmor", "event": "INCOMING_WEBHOOK_SANITIZED", "status": "ALLOWED", "ms": 12},
            {"tick": 2, "agent": "SentinelCommander", "event": "A2A_DISPATCH_SRE", "target": "SREAgent", "ms": 45},
            {"tick": 3, "agent": "SREAgent", "event": "SANDBOX_VERIFICATION_COMPLETE", "tests": "14/14 Green", "ms": 820},
            {"tick": 4, "agent": "JudgeAgent", "event": "EVALUATION_APPROVED", "score": 9.6, "ms": 1100},
            {"tick": 5, "agent": "CompyleEngine", "event": "SKILL_COMPILED_PROMOTED", "skill_id": "compiled-pool-scale", "ms": 1145},
        ]
    }

# --- 8. Full-Stack Static Assets & SPA Serving ---
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if not os.path.exists(static_dir):
    frontend_dist = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "dist"))
    if os.path.exists(frontend_dist):
        static_dir = frontend_dist

if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")




