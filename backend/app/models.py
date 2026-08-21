from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import enum

# --- Enums ---
class AgentRole(str, enum.Enum):
    COMMANDER = "commander"
    SRE = "sre"
    FINOPS = "finops"
    AUDITOR = "auditor"

class IncidentSeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class SecurityVerdict(str, enum.Enum):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    QUARANTINED = "QUARANTINED"

class ExecutionTier(str, enum.Enum):
    TIER_1_AUTONOMOUS = "TIER_1_AUTONOMOUS"       # Read-only / safe inspection
    TIER_2_CONSENSUS = "TIER_2_CONSENSUS"         # Dual-agent agreement required
    TIER_3_HUMAN_GATE = "TIER_3_HUMAN_GATE"       # Signed human approval required

# --- A2A Protocol Models ---
class AgentSkill(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any]
    is_compiled_skill: bool = False
    execution_time_ms: Optional[float] = None

class AgentCard(BaseModel):
    name: str
    role: AgentRole
    version: str = "1.0.0"
    description: str
    endpoints: Dict[str, str]
    skills: List[AgentSkill]
    security_schemes: List[str] = ["bearer_jwt"]

# --- Security & Model Armor Models ---
class ModelArmorScanRequest(BaseModel):
    session_id: str
    prompt: str
    user_identity: str = "engineer@enterprise.internal"
    source_ip: str = "127.0.0.1"

class ModelArmorScanResult(BaseModel):
    is_safe: bool
    verdict: SecurityVerdict
    sanitized_prompt: str
    detected_threats: List[str] = []
    redacted_pii: List[str] = []
    latency_ms: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

# --- Swarm Execution Models ---
class IncidentAlert(BaseModel):
    incident_id: str
    service_id: str
    severity: IncidentSeverity
    metric_name: str
    error_message: str
    telemetry_data: Dict[str, Any] = {}
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class RemediationAction(BaseModel):
    action_id: str
    tool_name: str
    parameters: Dict[str, Any]
    rationale: str
    tier: ExecutionTier = ExecutionTier.TIER_1_AUTONOMOUS
    code_diff: Optional[str] = None
    estimated_cost_delta_usd: float = 0.0

class JudgeEvaluation(BaseModel):
    score: float = Field(description="Safety & accuracy score from 0.0 to 10.0")
    is_approved: bool
    critique: str
    hallucination_detected: bool = False
    requires_human_signoff: bool = False

# --- D17 Human Approval & Audit Ledger ---
class ApprovalRecord(BaseModel):
    approval_id: str
    incident_id: str
    action_hash: str  # SHA-256 bound to action + parameters
    requested_action: RemediationAction
    status: str = "PENDING"  # PENDING | APPROVED | REJECTED
    signed_by: Optional[str] = None
    signed_at: Optional[str] = None

class AuditLogEntry(BaseModel):
    event_id: str
    session_id: str
    agent_name: str
    action_name: str
    status: str
    details: Dict[str, Any]
    model_armor_verdict: str = "ALLOWED"
    duration_ms: float
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

# --- Compyle Self-Compilation Models ---
class CompiledSkillManifest(BaseModel):
    skill_id: str
    skeleton_signature: str
    tool_sequence: List[str]
    input_slots: List[str]
    derived_edges: Dict[str, str]
    safety_preconditions: List[str]
    verified_by_judge: bool = True
    total_executions: int = 0
    total_tokens_saved: int = 0
