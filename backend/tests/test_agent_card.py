"""The A2A Agent Card served at the reserved well-known path.

The card previously carried an `endpoints` object instead of `url`, snake_case
keys, no protocolVersion, no capabilities, no declared modes, and skills with
neither id nor tags. All of those are required by the specification, so a
conforming client fetching the reserved path got something it could not parse.

Those were fixed against A2A v0.3. On 2026-08-26 Google's Agent Registry
refused the card outright: it was v0.3-shaped while declaring itself 1.0. The
TestA2AV1Conformance class at the bottom holds one test per rejection, and the
tests above were migrated to the v1.0 shape rather than deleted -- each still
guards the claim it was written for.
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
    "name", "description", "version", "supportedInterfaces",
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


def test_the_interface_url_is_absolute(card):
    """The interface url is where a client sends work. A path alone is not
    addressable. In v1.0 it lives inside supportedInterfaces, not at the top
    level, but the requirement it encodes is unchanged."""
    url = card["supportedInterfaces"][0]["url"]
    assert url.startswith("http")
    assert url.rstrip("/") != url.split("//")[0] + "//"


def test_no_snake_case_keys_survive_into_the_card(card):
    """The internal model uses snake_case; A2A is camelCase throughout. A
    stray `security_schemes` is invisible to a conforming client."""
    offenders = [k for k in card if "_" in k]
    assert offenders == [], f"snake_case keys leaked into the A2A card: {offenders}"


def test_security_schemes_is_a_map_of_typed_schemes(card):
    """It was a list of names, then a map of v0.3 `{type, scheme}` pairs.
    v1.0 types each scheme by wrapping it in its kind, and Agent Registry
    rejects the untyped form."""
    assert isinstance(card["securitySchemes"], dict)
    scheme = next(iter(card["securitySchemes"].values()))
    assert "type" not in scheme, "v0.3 untyped scheme leaked back in"
    assert scheme["httpAuthSecurityScheme"]["scheme"] == "bearer"


# ------------------------------------------------------------- not overclaiming

def test_streaming_is_not_claimed(card):
    """Incident progress streams over this service's own SSE endpoint, which
    is not the A2A `message/stream` method the flag refers to. Claiming it
    sends a conforming client to a method that does not exist."""
    assert card["capabilities"]["streaming"] is False
    assert card["capabilities"]["pushNotifications"] is False


def test_the_transport_is_declared_rather_than_defaulted(card):
    """Omitting the binding means JSONRPC by default, and this service exposes
    REST rather than the JSON-RPC method surface. v1.0 moved this into the
    interface entry; the claim it prevents is the same one."""
    assert card["supportedInterfaces"][0]["protocolBinding"] == "HTTP+JSON"


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

    assert response.json()["supportedInterfaces"][0]["url"].startswith("https://")


def test_a_plain_http_request_is_still_described_as_http():
    """Local development is genuinely http, and rewriting it would send a
    developer's client at a TLS port that is not listening."""
    response = client.get("/.well-known/agent-card.json")

    assert response.json()["supportedInterfaces"][0]["url"].startswith("http://")


def test_every_advertised_skill_exists_somewhere_in_the_code():
    """A skill name on an Agent Card is a promise a client can call it.

    Until 2026-08-25 the registry advertised six skills -- diagnose_telemetry_outage,
    synthesize_patch_and_verify, apply_scale_to_zero_caps among them -- and not
    one existed anywhere in the codebase. That is worse than dead code: this
    registry backs the document served at the A2A well-known URI, which is a
    machine-readable declaration of what a client may invoke.

    A name counts as real if it appears in app/ outside the registry that
    declares it -- as a method, or as a capability the Commander mints a token
    for.
    """
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent.parent / "app"
    registry_path = app_dir / "registry" / "a2a.py"
    sources = [
        p.read_text(encoding="utf-8")
        for p in app_dir.rglob("*.py")
        if p != registry_path
    ]

    fictional = []
    for card in AgentRegistry.list_all_cards():
        for skill in card.skills:
            if skill.is_compiled_skill:
                # Mined at runtime from real trajectories; nothing static to match.
                continue
            if not any(skill.name in src for src in sources):
                fictional.append(f"{card.name}.{skill.name}")

    assert fictional == [], (
        f"Agent Card advertises skills that exist nowhere in the code: "
        f"{fictional}. A client reading the card would go looking for them."
    )


# ------------------------------------------------------------ A2A v1.0 shape

class TestA2AV1Conformance:
    """Google's Agent Registry validates these.

    Each assertion below is one rejection it returned against the card this
    service served on 2026-08-26. The card called itself protocolVersion 1.0
    while carrying the v0.3 shape, so a v1.0 client could not parse it and the
    registry refused to store it at all.
    """

    def test_no_top_level_protocol_version(self, card):
        # "top-level protocolVersion is only supported for v0.3.x. For v1.x,
        #  omit this field and use supportedInterfaces instead."
        assert "protocolVersion" not in card

    def test_no_top_level_url(self, card):
        # "ambiguous Agent Card: both 'url' (v0.3) and 'supported_interfaces'
        #  (v1.0) are present"
        assert "url" not in card

    def test_supported_interfaces_carries_endpoint_and_binding(self, card):
        iface = card["supportedInterfaces"][0]
        assert iface["url"].startswith("http")
        assert iface["protocolBinding"] == "HTTP+JSON"
        assert iface["protocolVersion"] == "1.0"

    def test_no_v03_capabilities_survive(self, card):
        # "unknown field stateTransitionHistory"
        caps = card["capabilities"]
        assert "stateTransitionHistory" not in caps
        assert set(caps) <= {
            "streaming", "pushNotifications", "extendedAgentCard", "extensions",
        }

    def test_security_is_not_advertised_under_its_v03_name(self, card):
        # "unknown field security" -- v1.0 calls it securityRequirements.
        assert "security" not in card


# --------------------------------------------------------- upstream catalogue

def test_the_registry_service_id_does_not_stutter():
    """SyntruenoCommander must not become syntrueno-syntruenocommander.

    It did, on the first registration run, and produced a duplicate catalogue
    entry beside the correctly-named one.
    """
    from app.registry.agent_card import registry_service_id

    assert registry_service_id("SyntruenoCommander") == "syntrueno-commander"
    assert registry_service_id("SREAgent") == "syntrueno-sreagent"


def test_the_advertised_upstream_ids_are_the_ones_the_script_creates():
    """/a2a/v1/registry names entries in Google's Agent Registry.

    Both sides derive the id from the same helper. If that ever forks, the API
    would advertise catalogue entries that were never created -- a broken
    discovery claim, which is the failure this whole document exists to avoid.
    """
    from app.registry.agent_card import registry_service_id

    advertised = client.get("/a2a/v1/registry").json()["upstream_registry"]
    expected = {
        registry_service_id(c.name) for c in AgentRegistry.list_all_cards()
    }
    assert {s.rsplit("/", 1)[-1] for s in advertised["services"]} == expected
    assert advertised["location"] == "us-central1", (
        "Agent Registry lives beside Agent Engine in us-central1, not at the "
        "'global' location Gemini uses"
    )
