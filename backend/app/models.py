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
    session_id: str = "session-active"
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

class RemediationTool(str, enum.Enum):
    """The complete remediation surface. This enum IS the security boundary.

    It is handed to Gemini as the response schema, so the model's action space
    is closed by construction: there is no destructive verb for a prompt
    injection to reach for, because no destructive verb exists here. Filtering
    a bad tool call is a weaker guarantee than making it unrepresentable.
    """

    UPDATE_RESOURCES = "update_cloud_run_resources"     # memory / cpu
    UPDATE_SCALING = "update_cloud_run_scaling"         # min / max instances
    RECYCLE_REVISION = "recycle_cloud_run_revision"     # rolling restart
    RECONFIGURE_POOL = "reconfigure_connection_pool"    # DB pool config
    NO_ACTION = "no_action_required"


class SreRemediationPlan(BaseModel):
    """The schema Gemini fills in when diagnosing an incident."""

    root_cause: str = Field(
        description="The specific technical cause, grounded in the supplied "
        "telemetry. State what the evidence shows, not what is typical."
    )
    confidence: float = Field(
        description="0.0-1.0 confidence in this root cause given the evidence available."
    )
    recommended_tool: RemediationTool = Field(
        description="Which remediation to apply. Choose no_action_required if "
        "the telemetry does not justify a change."
    )
    rationale: str = Field(
        description="Why this specific remediation addresses the root cause."
    )
    target_memory: Optional[str] = Field(
        default=None, description="e.g. '1Gi'. Only for update_cloud_run_resources."
    )
    target_cpu: Optional[str] = Field(
        default=None, description="e.g. '1'. Only for update_cloud_run_resources."
    )
    target_min_instances: Optional[int] = Field(
        default=None, description="Only for update_cloud_run_scaling."
    )
    target_max_instances: Optional[int] = Field(
        default=None, description="Only for update_cloud_run_scaling."
    )
    target_pool_size: Optional[int] = Field(
        default=None, description="Only for reconfigure_connection_pool."
    )
    code_diff: Optional[str] = Field(
        default=None, description="Unified diff of the config change, if applicable."
    )
    estimated_monthly_cost_delta_usd: float = Field(
        default=0.0, description="Negative means this saves money."
    )


class JudgeRubric(BaseModel):
    """The schema Gemini fills in. Kept free of server-side fields so the
    response schema sent to the model stays minimal and unambiguous."""

    score: float = Field(
        description="Safety and accuracy score from 0.0 to 10.0. Be strict: "
        "a plausible-looking change with an unverified blast radius scores below 5."
    )
    is_approved: bool = Field(
        description="True only if this action is safe to execute as written."
    )
    critique: str = Field(
        description="Specific technical reasoning. Name the concrete failure mode "
        "if there is one; do not hedge."
    )
    hallucination_detected: bool = Field(
        default=False,
        description="True if the proposed action references resources, metrics, "
        "or APIs that were not present in the incident context.",
    )
    requires_human_signoff: bool = Field(
        default=False,
        description="True if this action changes production capacity, is not "
        "trivially reversible, or carries meaningful blast radius.",
    )


class JudgeEvaluation(JudgeRubric):
    """Full internal verdict: the model's rubric plus measured server facts."""

    degraded: bool = False
    degraded_reason: Optional[str] = None
    telemetry: Dict[str, Any] = {}

# --- D17 Human Approval & Audit Ledger ---
class ApprovalRecord(BaseModel):
    approval_id: str
    incident_id: str
    action_hash: str  # SHA-256 bound to tool + parameters + tier
    requested_action: RemediationAction
    status: str = "PENDING"  # PENDING | APPROVED | REJECTED
    signed_by: Optional[str] = None
    signed_at: Optional[str] = None

    # A signature authorises one execution, once, for a bounded window.
    # Without these, a signed approval would authorise the same action forever:
    # sign a memory bump today and the swarm could replay it unprompted next
    # week, because the hash still matches.
    consumed_at: Optional[str] = None
    consumed_by_action_id: Optional[str] = None
    expires_at: Optional[str] = None

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
