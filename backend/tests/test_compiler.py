"""ThorForja mining and dispatch.

The earlier implementation reported constants as measurements, marked every
manifest judge-verified, and returned COMPILED_SKILL_SUCCESS without executing
anything. These tests pin the properties that stop it drifting back.
"""

import pytest

from app.compiler.engine import ThorForjaEngine
from app.compiler.recorder import TrajectoryRecorder


def _record(incident_id, tools=("diagnose", "update_cloud_run_resources"),
            approved=True, score=8.5, tokens=1200, params=None):
    return TrajectoryRecorder.record_trajectory(
        incident_type="container/memory/utilization",
        tool_sequence=list(tools),
        parameters=params if params is not None else {"service_id": "canary",
                                                      "memory": "1Gi"},
        duration_ms=10.0,
        incident_id=incident_id,
        judge_score=score,
        judge_approved=approved,
        diagnosis_tokens=tokens,
    )


@pytest.fixture(autouse=True)
def _clean():
    TrajectoryRecorder.clear()
    ThorForjaEngine.clear()
    yield
    TrajectoryRecorder.clear()
    ThorForjaEngine.clear()


# ------------------------------------------------------------------ mining

def test_one_incident_recorded_twice_is_not_a_pattern():
    """Counting rows rather than incidents makes a Pub/Sub redelivery, or a
    replayed demo, look exactly like a recurring trajectory."""
    _record("inc-1")
    _record("inc-1")

    assert ThorForjaEngine.mine_and_compile() == []


def test_two_distinct_incidents_compile():
    _record("inc-1")
    _record("inc-2")

    compiled = ThorForjaEngine.mine_and_compile()

    assert len(compiled) == 1
    assert compiled[0].distinct_incidents == 2
    assert compiled[0].occurrences == 2


def test_input_slots_are_the_keys_every_occurrence_carried():
    """Taking the first sample's keys promotes a one-off parameter into part
    of the skill's shape, and the dispatcher then demands it forever."""
    _record("inc-1", params={"service_id": "canary", "memory": "1Gi"})
    _record("inc-2", params={"service_id": "canary", "cpu": "2"})

    manifest = ThorForjaEngine.mine_and_compile()[0]

    assert manifest.input_slots == ["service_id"]


# -------------------------------------------------------------- verification

def test_verification_requires_every_trajectory_to_have_been_approved():
    _record("inc-1", approved=True)
    _record("inc-2", approved=False)

    assert ThorForjaEngine.mine_and_compile()[0].verified_by_judge is False


def test_an_unjudged_trajectory_is_not_treated_as_approved():
    """Unknown is not approved. Defaulting it is how the old manifest came to
    claim verification nothing had performed."""
    _record("inc-1", approved=True)
    _record("inc-2", approved=None, score=None)

    manifest = ThorForjaEngine.mine_and_compile()[0]

    assert manifest.verified_by_judge is False
    assert manifest.min_judge_score == 8.5   # the only score there was


# ------------------------------------------------------------- measurement

def test_token_saving_is_the_measured_mean_not_a_constant():
    """It used to credit itself a flat 3200 per call, from a comment saying
    "approx"."""
    _record("inc-1", tokens=1000)
    _record("inc-2", tokens=2000)

    manifest = ThorForjaEngine.mine_and_compile()[0]

    assert manifest.mean_diagnosis_tokens == 1500


def test_nothing_measured_means_nothing_claimed():
    _record("inc-1", tokens=None)
    _record("inc-2", tokens=None)

    manifest = ThorForjaEngine.mine_and_compile()[0]

    assert manifest.mean_diagnosis_tokens == 0
    result = ThorForjaEngine.propose(manifest.skeleton_signature,
                                     {"service_id": "canary", "memory": "1Gi"})
    assert result["tokens_saved"] == 0


def test_reported_latency_is_measured():
    """latency_ms was the literal 11.8 on every call."""
    _record("inc-1")
    _record("inc-2")
    sig = ThorForjaEngine.mine_and_compile()[0].skeleton_signature

    inputs = {"service_id": "canary", "memory": "1Gi"}
    runs = [ThorForjaEngine.propose(sig, inputs) for _ in range(8)]

    assert all(r["status"] == "PROPOSED" for r in runs)
    assert all(r["latency_ms"] > 0 for r in runs)
    # Sampled rather than compared pairwise: two timings of trivial work can
    # legitimately land on the same value, but eight identical ones mean the
    # number is not being measured at all.
    assert len({r["latency_ms"] for r in runs}) > 1


# ---------------------------------------------------------------- dispatch

def test_dispatch_proposes_and_does_not_claim_to_have_executed():
    """A skill that could act on its own would be a route around the Judge and
    the human gate, opened by getting a sequence to repeat."""
    _record("inc-1")
    _record("inc-2")
    sig = ThorForjaEngine.mine_and_compile()[0].skeleton_signature

    result = ThorForjaEngine.propose(sig, {"service_id": "canary", "memory": "1Gi"})

    assert result["status"] == "PROPOSED"
    assert result["requires_judgement"] is True
    assert result["requires_human_gate_if_tier_3"] is True
    assert result["llm_calls_made"] == 0
    assert "executed_tools" not in result


def test_missing_inputs_are_refused_not_invented():
    """Filling a missing service_id is how a skill mined against the canary
    ends up pointed somewhere else."""
    _record("inc-1", params={"service_id": "canary", "memory": "1Gi"})
    _record("inc-2", params={"service_id": "canary", "memory": "2Gi"})
    manifest = ThorForjaEngine.mine_and_compile()[0]

    result = ThorForjaEngine.propose(manifest.skeleton_signature,
                                     {"service_id": "canary"})

    assert result["status"] == "REFUSED_INCOMPLETE_INPUTS"
    assert result["missing_slots"] == ["memory"]
    # A refusal is not an execution.
    assert manifest.total_executions == 0


def test_an_unknown_signature_is_not_a_skill():
    assert ThorForjaEngine.propose("never->compiled", {}) is None
