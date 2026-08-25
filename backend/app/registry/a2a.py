from typing import Dict, List, Optional
from app.models import AgentCard, AgentRole, AgentSkill

class AgentRegistry:
    """Central registry serving Agent-to-Agent (A2A) protocol agent cards."""
    
    _registry: Dict[str, AgentCard] = {}

    @classmethod
    def register_agent(cls, card: AgentCard):
        cls._registry[card.role.value] = card

    @classmethod
    def get_agent_card(cls, role: AgentRole) -> Optional[AgentCard]:
        return cls._registry.get(role.value)

    @classmethod
    def list_all_cards(cls) -> List[AgentCard]:
        return list(cls._registry.values())

    @classmethod
    def register_compiled_skill_for_role(cls, role: AgentRole, skill: AgentSkill):
        card = cls._registry.get(role.value)
        if card:
            # Replace if already exists or append
            card.skills = [s for s in card.skills if s.name != skill.name]
            card.skills.append(skill)

# Initialize standard swarm cards
AgentRegistry.register_agent(
    AgentCard(
        name="SyntruenoCommander",
        role=AgentRole.COMMANDER,
        description="Master Socratic coordinator and A2A swarm dispatcher",
        endpoints={"a2a": "/a2a/v1/commander", "card": "/.well-known/agent-card.json"},
        skills=[
            AgentSkill(
                name="coordinate_incident_response",
                description="Coordinates incident diagnosis across SRE, FinOps, and Auditor sub-agents",
                input_schema={"type": "object", "properties": {"incident_id": {"type": "string"}}},
            )
        ],
    )
)

AgentRegistry.register_agent(
    AgentCard(
        name="SREAgent",
        role=AgentRole.SRE,
        description="Autonomous SRE incident remediation and code patch synthesis agent",
        endpoints={"a2a": "/a2a/v1/sre"},
        skills=[
            AgentSkill(
                name="diagnose_telemetry_outage",
                description="Diagnoses container bottlenecks, memory leaks, and connection pool exhaustion",
                input_schema={"type": "object", "properties": {"service_id": {"type": "string"}}},
            ),
            AgentSkill(
                name="synthesize_patch_and_verify",
                description="Generates surgical configuration/code fixes and verifies in sandbox",
                input_schema={"type": "object", "properties": {"service_id": {"type": "string"}, "root_cause": {"type": "string"}}},
            ),
        ],
    )
)

AgentRegistry.register_agent(
    AgentCard(
        name="FinOpsAgent",
        role=AgentRole.FINOPS,
        description="Autonomous cloud financial engineering and scale-to-zero optimizer",
        endpoints={"a2a": "/a2a/v1/finops"},
        skills=[
            AgentSkill(
                name="audit_cloud_spending",
                description="Compares configured Cloud Run limits against measured utilisation and prices the gap from the Cloud Billing Catalog",
                input_schema={"type": "object", "properties": {"time_window": {"type": "string"}}},
            ),
            AgentSkill(
                name="apply_scale_to_zero_caps",
                description="Enforces zero-instance idle scaling on non-production Cloud Run services",
                input_schema={"type": "object", "properties": {"service_id": {"type": "string"}}},
            ),
        ],
    )
)

AgentRegistry.register_agent(
    AgentCard(
        name="AuditorAgent",
        role=AgentRole.AUDITOR,
        description="Gemini-backed LLM-as-a-Judge and D17 cryptographic approval gate",
        endpoints={"a2a": "/a2a/v1/auditor"},
        skills=[
            AgentSkill(
                name="evaluate_remediation_safety",
                description="Critiques proposed cloud actions on a 10-point scale for safety and idempotency",
                input_schema={"type": "object", "properties": {"action_id": {"type": "string"}}},
            )
        ],
    )
)
