"""The A2A Agent Card served at the reserved well-known path.

The card previously carried an `endpoints` object instead of `url`, snake_case
keys, no protocolVersion, no capabilities, no declared modes, and skills with
neither id nor tags. All of those are required by the specification, so a
conforming client fetching the reserved path got something it could not parse.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import AgentRole
from app.registry.a2a import AgentRegistry
from app.registry.agent_card import A2A_PROTOCOL_VERSION, to_a2a_agent_card

client = TestClient(app)

# A2A AgentCard, required top-level fields.
REQUIRED_CARD_FIELDS = [
    "protocolVersion", "name", "description", "url", "version",
    "capabilities", "defaultInputModes", "defaultOutputModes", "skills",
]

# A2A AgentSkill, required fields.
REQUIRED_SKILL_FIELDS = ["id", "name", "description", "tags"]


@pytest.fixture
def card():
    return client.get("/.well-known/agent-card.json").json()


def test_the_card_carries_every_required_field(card):
    missing = [f for f in REQUIRED_CARD_FIELDS if f not in card]
    assert missing == [], f"card is missing required A2A fields: {missing}"


def test_every_skill_carries_every_required_field(card):
    assert card["skills"], "a card with no skills advertises nothing"
    for skill in card["skills"]:
        missing = [f for f in REQUIRED_SKILL_FIELDS if f not in skill]
        assert missing == [], f"skill {skill.get('name')} missing {missing}"
        assert skill["tags"], "tags are required and must not be empty"


def test_the_protocol_version_omits_the_patch_number():
    """The spec is explicit that patch versions should not appear in cards."""
    assert A2A_PROTOCOL_VERSION.count(".") == 1
    assert A2A_PROTOCOL_VERSION == "1.0"


def test_the_url_is_absolute(card):
    """`url` is where a client sends work. A path alone is not addressable."""
    assert card["url"].startswith("http")
    assert card["url"].rstrip("/") != card["url"].split("//")[0] + "//"


def test_no_snake_case_keys_survive_into_the_card(card):
    """The internal model uses snake_case; A2A is camelCase throughout. A
    stray `security_schemes` is invisible to a conforming client."""
    offenders = [k for k in card if "_" in k]
    assert offenders == [], f"snake_case keys leaked into the A2A card: {offenders}"


def test_security_schemes_is_a_map_not_a_list(card):
    """It was a list of names. The spec defines a map of name to scheme
    object, and a list carries no scheme definition at all."""
    assert isinstance(card["securitySchemes"], dict)
    scheme = next(iter(card["securitySchemes"].values()))
    assert scheme["type"] == "http"
    assert scheme["scheme"] == "bearer"


# ------------------------------------------------------------- not overclaiming

def test_streaming_is_not_claimed(card):
    """Incident progress streams over this service's own SSE endpoint, which
    is not the A2A `message/stream` method the flag refers to. Claiming it
    sends a conforming client to a method that does not exist."""
    assert card["capabilities"]["streaming"] is False
    assert card["capabilities"]["pushNotifications"] is False


def test_the_transport_is_declared_rather_than_defaulted(card):
    """Omitting preferredTransport means JSONRPC by default, and this service
    exposes REST rather than the JSON-RPC method surface."""
    assert card["preferredTransport"] == "HTTP+JSON"


def test_every_registered_agent_renders_a_valid_card():
    """The commander is what the well-known path serves, but the registry
    holds four and any of them may be advertised."""
    for role in AgentRole:
        internal = AgentRegistry.get_agent_card(role)
        if internal is None:
            continue
        rendered = to_a2a_agent_card(internal, "https://example.test")
        missing = [f for f in REQUIRED_CARD_FIELDS if f not in rendered]
        assert missing == [], f"{role.value}: missing {missing}"
        for skill in rendered["skills"]:
            assert all(f in skill for f in REQUIRED_SKILL_FIELDS)


def test_a_compiled_skill_is_tagged_as_one():
    """Deterministic and model-free is exactly what a client choosing between
    agents would filter on."""
    from app.models import AgentSkill

    internal = AgentRegistry.get_agent_card(AgentRole.SRE)
    before = len(internal.skills)
    AgentRegistry.register_compiled_skill_for_role(
        role=AgentRole.SRE,
        skill=AgentSkill(name="compiled_probe", description="d",
                         input_schema={}, is_compiled_skill=True),
    )
    try:
        rendered = to_a2a_agent_card(
            AgentRegistry.get_agent_card(AgentRole.SRE), "https://example.test")
        compiled = [s for s in rendered["skills"] if s["name"] == "compiled_probe"]
        assert compiled and "compiled" in compiled[0]["tags"]
    finally:
        internal.skills = internal.skills[:before]


def test_the_advertised_url_honours_the_forwarded_scheme():
    """Cloud Run terminates TLS at its proxy and forwards plain HTTP, so the
    request reports http:// on a service only reachable over https://.
    A discovery document is the worst place to propagate that."""
    response = client.get("/.well-known/agent-card.json",
                          headers={"X-Forwarded-Proto": "https"})

    assert response.json()["url"].startswith("https://")


def test_a_plain_http_request_is_still_described_as_http():
    """Local development is genuinely http, and rewriting it would send a
    developer's client at a TLS port that is not listening."""
    response = client.get("/.well-known/agent-card.json")

    assert response.json()["url"].startswith("http://")
