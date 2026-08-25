"""Serialises the internal registry into a conformant A2A Agent Card.

The card is published at ``/.well-known/agent-card.json``, which is the location
the A2A specification reserves for it. Publishing there is itself a claim: a
client that fetches that path expects a document matching the A2A schema, and
ours did not. It carried an ``endpoints`` object instead of ``url``, snake_case
keys throughout, no ``protocolVersion``, no ``capabilities``, no declared input
or output modes, and skills with neither ``id`` nor ``tags``. Every one of those
is required. The card was readable by a person and unparseable by an A2A client,
which is the wrong way round for a machine-readable discovery document.

Two decisions worth stating, because both are about not overclaiming:

**The transport is declared as HTTP+JSON, not JSONRPC.** JSONRPC is the A2A
default and would be assumed if ``preferredTransport`` were omitted. This
service exposes REST endpoints, not the JSON-RPC method surface, so saying
JSONRPC would send a conforming client to methods that do not exist.

**``capabilities.streaming`` is false.** Incident progress does stream over SSE
at ``/api/v1/swarm/incident/stream``, but that is this service's own endpoint,
not the A2A ``message/stream`` method. The flag means the latter. Setting it
true because "we stream, technically" is exactly the kind of claim this project
spends the rest of its code refusing to make.

The internal ``AgentCard`` model stays as it is. It backs the operations console
and the registry endpoint, and those have no reason to move to protocol shapes.
This module is the adapter at the public boundary.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from app.models import AgentCard, AgentRole, AgentSkill

# Major.Minor only. The spec is explicit that patch numbers should not appear
# in agent cards.
A2A_PROTOCOL_VERSION = "1.0"

# Tags let a client filter agents by what they do, and are required on every
# skill. Derived from the role rather than invented per skill so they stay
# consistent as skills are added.
_ROLE_TAGS: Dict[AgentRole, List[str]] = {
    AgentRole.COMMANDER: ["orchestration", "incident-response"],
    AgentRole.SRE: ["sre", "diagnosis", "remediation"],
    AgentRole.FINOPS: ["finops", "cost-optimization"],
    AgentRole.AUDITOR: ["safety", "evaluation", "approval"],
}


def _skill_id(name: str) -> str:
    """A stable, URL-safe id. Skill names are already snake_case identifiers."""
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")


def _to_a2a_skill(skill: AgentSkill, role: AgentRole) -> Dict[str, Any]:
    tags = list(_ROLE_TAGS.get(role, []))
    if skill.is_compiled_skill:
        # Worth surfacing: a compiled skill is deterministic and costs no model
        # call, which is the sort of thing a client selecting between agents
        # would want to filter on.
        tags.append("compiled")

    entry: Dict[str, Any] = {
        "id": _skill_id(skill.name),
        "name": skill.name,
        "description": skill.description,
        "tags": tags,
    }

    # inputModes/outputModes are optional and override the card defaults. There
    # is nothing to override here -- every skill takes and returns JSON -- so
    # they are omitted rather than restated.
    return entry


def to_a2a_agent_card(card: AgentCard, base_url: str) -> Dict[str, Any]:
    """Render one registry entry as an A2A ``AgentCard``.

    ``base_url`` is the externally reachable origin. It is taken from the
    request rather than configuration so the card is correct on Cloud Run and
    on localhost without either needing to be told about the other.
    """
    path = card.endpoints.get("a2a", "/")
    return {
        "protocolVersion": A2A_PROTOCOL_VERSION,
        "name": card.name,
        "description": card.description,
        "url": f"{base_url.rstrip('/')}{path}",
        "version": card.version,
        "preferredTransport": "HTTP+JSON",
        "provider": {
            "organization": "Syntrueno",
            "url": "https://github.com/Shaan-alpha/syntrueno",
        },
        "documentationUrl": f"{base_url.rstrip('/')}/docs",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [_to_a2a_skill(s, card.role) for s in card.skills],
        # A map keyed by scheme name, per the spec -- not the list of names the
        # previous card carried. Every dispatch between agents must present a
        # capability token scoped to the one skill being invoked.
        "securitySchemes": {
            "a2aCapabilityToken": {
                "type": "http",
                "scheme": "bearer",
                "description": (
                    "Short-lived HMAC capability token, scoped to a single "
                    "skill and minted per dispatch by the Commander."
                ),
            }
        },
        "security": [{"a2aCapabilityToken": []}],
    }
