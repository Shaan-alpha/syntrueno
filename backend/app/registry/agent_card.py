"""Serialises the internal registry into a conformant A2A Agent Card.

The card is published at ``/.well-known/agent-card.json``, which is the location
the A2A specification reserves for it. Publishing there is itself a claim: a
client that fetches that path expects a document matching the A2A schema, and
ours did not. It carried an ``endpoints`` object instead of ``url``, snake_case
keys throughout, no ``protocolVersion``, no ``capabilities``, no declared input
or output modes, and skills with neither ``id`` nor ``tags``. Every one of those
is required. The card was readable by a person and unparseable by an A2A client,
which is the wrong way round for a machine-readable discovery document.

Those repairs targeted A2A v0.3. The card then declared ``protocolVersion:
"1.0"`` while keeping the v0.3 shape, which is not a version mismatch a client
can shrug off -- Google's Agent Registry rejected the document four times on
2026-08-26, once per field, and would not store it at all. The renderer below
emits v1.0: the endpoint, its binding and the protocol version live inside
``supportedInterfaces``, ``stateTransitionHistory`` is gone, and each security
scheme is wrapped in its kind.

Two decisions worth stating, because both are about not overclaiming:

**The transport is declared as HTTP+JSON, not JSONRPC.** JSONRPC is the A2A
default and would be assumed if the binding were omitted. This service exposes
REST endpoints, not the JSON-RPC method surface, so saying JSONRPC would send a
conforming client to methods that do not exist. In v1.0 this is
``protocolBinding`` inside ``supportedInterfaces`` rather than a top-level
``preferredTransport``.

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
#
# In v1.0 this belongs INSIDE supportedInterfaces, never at the top level. A
# top-level protocolVersion marks the document as v0.3 no matter what value it
# carries, which is how this card spent a week calling itself 1.0 while being
# shaped like 0.3. Google's Agent Registry rejects that outright:
#   "top-level protocolVersion is only supported for v0.3.x. For v1.x, omit
#    this field and use supportedInterfaces instead."
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
        "name": card.name,
        "description": card.description,
        "version": card.version,
        # v1.0 collapses url + preferredTransport + protocolVersion into one
        # ordered list, first entry preferred. Carrying the old top-level `url`
        # alongside this is not merely redundant -- the registry rejects the
        # card as "ambiguous: both 'url' (v0.3) and 'supported_interfaces'
        # (v1.0) are present".
        "supportedInterfaces": [
            {
                "url": f"{base_url.rstrip('/')}{path}",
                # Not JSONRPC. That is the A2A default and would be assumed if
                # this were omitted, sending a conforming client to a JSON-RPC
                # method surface this service does not expose.
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": A2A_PROTOCOL_VERSION,
            }
        ],
        "provider": {
            "organization": "Syntrueno",
            "url": "https://github.com/Shaan-alpha/syntrueno",
        },
        "documentationUrl": f"{base_url.rstrip('/')}/docs",
        # v1.0 dropped stateTransitionHistory. Listing it did not make the card
        # merely inaccurate, it made the whole document fail to parse.
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [_to_a2a_skill(s, card.role) for s in card.skills],
        # v1.0 types each scheme by wrapping it in its kind, rather than the
        # v0.3 `{"type": "http", "scheme": "bearer"}` pair.
        "securitySchemes": {
            "a2aCapabilityToken": {
                "httpAuthSecurityScheme": {
                    "scheme": "bearer",
                    "description": (
                        "Short-lived HMAC capability token, scoped to a single "
                        "skill and minted per dispatch by the Commander."
                    ),
                }
            }
        },
        # The matching requirement list is deliberately absent. v1.0 renames
        # v0.3's `security` to `securityRequirements`, and Agent Registry's
        # validator rejects both (probed 2026-08-26: the scheme map above is
        # accepted, either requirement key is not). So the card declares what
        # the scheme IS and stays silent on where it is demanded, rather than
        # carrying a field that makes the whole document fail to parse.
    }
