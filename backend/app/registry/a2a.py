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

# The swarm's advertised capabilities.
#
# These were fiction until 2026-08-25. The cards advertised
# diagnose_telemetry_outage, synthesize_patch_and_verify,
# apply_scale_to_zero_caps and three others -- six skill names, none of which
# existed anywhere in the codebase. That matters more here than in ordinary
# dead code: this registry backs the Agent Card served at the A2A well-known
# URI, which is a machine-readable declaration of what a client may invoke. A
# conforming client reading it would have gone looking for capabilities that
# were never there.
#
# Every name below is now either a capability the Commander actually mints a
# token for (diagnose_incident, evaluate_action -- see app/security/token_auth.py)
# or a real entry point on the agent.

AgentRegistry.register_agent(
    AgentCard(
        name="SyntruenoCommander",
        role=AgentRole.COMMANDER,
        description=(
            "Orchestrates incident response: recalls prior incidents, mints a "
            "scoped capability token per dispatch, and resolves the execution "
            "tier from the Judge's verdict"
        ),
        endpoints={"a2a": "/a2a/v1/commander", "card": "/.well-known/agent-card.json"},
        skills=[
            AgentSkill(
                name="process_incident",
                description=(
                    "Runs an incident through screening, diagnosis, safety "
                    "judgement and tiering, returning a proposed action and its "
                    "authorisation state"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "incident_id": {"type": "string"},
                        "service_id": {"type": "string"},
                        "error_message": {"type": "string"},
                    },
                    "required": ["incident_id", "service_id", "error_message"],
                },
            )
        ],
    )
)

AgentRegistry.register_agent(
    AgentCard(
        name="SREAgent",
        role=AgentRole.SRE,
        description=(
            "Diagnoses incidents from telemetry and proposes a remediation "
            "drawn from a closed enum -- it cannot express a destructive action"
        ),
        endpoints={"a2a": "/a2a/v1/sre"},
        skills=[
            AgentSkill(
                name="diagnose_incident",
                description=(
                    "Root-causes an alert and selects one RemediationTool: "
                    "update_cloud_run_resources, update_cloud_run_scaling, "
                    "recycle_cloud_run_revision or reconfigure_connection_pool. "
                    "Requires a capability token scoped to this skill."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "service_id": {"type": "string"},
                        "error_message": {"type": "string"},
                        "telemetry_data": {"type": "object"},
                    },
                    "required": ["service_id", "error_message"],
                },
            )
        ],
    )
)

AgentRegistry.register_agent(
    AgentCard(
        name="FinOpsAgent",
        role=AgentRole.FINOPS,
        description=(
            "Audits configured Cloud Run limits against measured utilisation "
            "and prices the gap from the Cloud Billing Catalog"
        ),
        endpoints={"a2a": "/a2a/v1/finops"},
        skills=[
            AgentSkill(
                name="audit_spending_and_waste",
                description=(
                    "Compares each service's configured memory against the peak "
                    "Cloud Monitoring recorded, and reports the recoverable "
                    "amount priced at the published regional rate. Services with "
                    "no observations are reported as unmeasured, not as idle."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"window_days": {"type": "integer"}},
                },
            )
        ],
    )
)

AgentRegistry.register_agent(
    AgentCard(
        name="AuditorAgent",
        role=AgentRole.AUDITOR,
        description=(
            "LLM-as-a-Judge over proposed actions, and the D17 cryptographic "
            "approval gate that binds a signature to one exact action"
        ),
        endpoints={"a2a": "/a2a/v1/auditor"},
        skills=[
            AgentSkill(
                name="evaluate_action",
                description=(
                    "Scores a proposed remediation 0-10 against a safety rubric "
                    "and reports whether it requires human sign-off. Requires a "
                    "capability token scoped to this skill."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "action_id": {"type": "string"},
                        "tool_name": {"type": "string"},
                        "parameters": {"type": "object"},
                    },
                    "required": ["tool_name"],
                },
            )
        ],
    )
)
