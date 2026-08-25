import pytest
from app.models import (
    AgentCard,
    AgentRole,
    AgentSkill,
    IncidentAlert,
    IncidentSeverity,
    SecurityVerdict,
    ModelArmorScanResult,
    RemediationAction,
    ExecutionTier,
    JudgeEvaluation,
    ApprovalRecord,
    CompiledSkillManifest,
)

def test_agent_card_schema():
    card = AgentCard(
        name="SREAgent",
        role=AgentRole.SRE,
        description="Autonomous SRE incident remediation agent",
        endpoints={"a2a": "https://sentinel.run.app/a2a/v1/sre"},
        skills=[
            AgentSkill(
                name="diagnose_container_pool",
                description="Diagnoses connection pool starvation",
                input_schema={"type": "object", "properties": {"service_id": {"type": "string"}}},
            )
        ],
    )
    assert card.role == AgentRole.SRE
    assert len(card.skills) == 1
    assert card.skills[0].name == "diagnose_container_pool"

def test_incident_alert_parsing(sample_incident_payload):
    alert = IncidentAlert(**sample_incident_payload)
    assert alert.incident_id == "inc-9021"
    assert alert.severity == IncidentSeverity.CRITICAL
    assert alert.telemetry_data["active_connections"] == 98

def test_model_armor_scan_result():
    scan = ModelArmorScanResult(
        is_safe=False,
        verdict=SecurityVerdict.BLOCKED,
        sanitized_prompt="",
        detected_threats=["prompt_injection_pattern_detected"],
        latency_ms=14.2,
    )
    assert scan.is_safe is False
    assert scan.verdict == SecurityVerdict.BLOCKED
    assert len(scan.detected_threats) == 1

def test_compiled_skill_manifest():
    manifest = CompiledSkillManifest(
        skill_id="skill-db-pool-v1",
        skeleton_signature="check_pool->scale_config->verify_health",
        tool_sequence=["check_pool", "scale_config", "verify_health"],
        input_slots=["service_id", "target_pool_size"],
        safety_preconditions=["judge.evaluate_action", "human_gate.binding"],
        verified_by_judge=False,
    )
    assert manifest.skill_id == "skill-db-pool-v1"
    assert len(manifest.tool_sequence) == 3
    assert manifest.total_tokens_saved == 0


def test_a_manifest_cannot_default_to_verified():
    """verified_by_judge defaulted to True, so a skill nothing had checked was
    indistinguishable from one the Judge had approved twice."""
    import pytest as _pytest
    from pydantic import ValidationError

    with _pytest.raises(ValidationError):
        CompiledSkillManifest(
            skill_id="s", skeleton_signature="a", tool_sequence=["a"],
            input_slots=[], safety_preconditions=[],
        )


def test_every_setting_is_actually_read_somewhere():
    """A declared setting that nothing consumes is a promise the code does not keep.

    This has happened five times in this project. USE_VERTEX_AI and
    USE_REAL_MODEL_ARMOR both sat in config for weeks looking like working
    toggles while nothing branched on them. ENGINE_NAME,
    GOOGLE_CLOUD_PROJECT_NUMBER and MAX_CONCURRENT_TASKS were documented in
    .env.example and read by nothing -- the last of those reads like a
    concurrency limit and enforced no limit at all.

    A setting counts as used if anything references it outside its own
    declaration, including config.py's own properties and helpers.
    """
    import re
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent.parent / "app"
    config_path = app_dir / "config.py"
    config_src = config_path.read_text(encoding="utf-8")

    declaration = re.compile(r"^    ([A-Z][A-Z0-9_]*)\s*:\s*[^=]+=", re.M)
    declared = declaration.findall(config_src)
    assert declared, "no settings parsed -- the declaration pattern has drifted"

    sources = [p.read_text(encoding="utf-8") for p in app_dir.rglob("*.py")]

    unused = []
    for name in declared:
        hits = sum(src.count(name) for src in sources)
        # Its own declaration is one hit; anything above that is a real read.
        if hits <= 1:
            unused.append(name)

    assert unused == [], (
        f"settings declared but never read: {unused}. Either wire them up or "
        "delete them -- a config flag that does nothing is worse than absent, "
        "because a reader assumes it works."
    )
