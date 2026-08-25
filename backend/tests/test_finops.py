"""FinOps auditing.

The previous agent returned three invented resources totalling an invented
$440/month, from a docstring claiming it queried BigQuery billing records. It
queried nothing. These tests hold the properties that make the replacement's
numbers worth reading, and none of them touch the network.
"""

import pytest

from app.agents.finops import HEADROOM_MULTIPLIER, FinOpsAgent, _parse_memory_mib
from app.cloud.pricing import CloudRunPricing
from app.cloud.runadmin import CloudRunAdmin
from app.cloud.usage import ServiceUsage


def _services(*entries):
    return {"available": True, "services": list(entries)}


def _svc(name, memory="1Gi", min_instances=1):
    return {"service": name, "memory": memory, "cpu": "1",
            "min_instances": min_instances, "max_instances": 1}


@pytest.fixture
def audit(monkeypatch):
    """Drive the agent against supplied listings, usage and rates."""
    def run(services, usage, memory_rate=0.0000025):
        monkeypatch.setattr(CloudRunAdmin, "list_services",
                            classmethod(lambda cls: services))
        monkeypatch.setattr(ServiceUsage, "peak_utilization",
                            classmethod(lambda cls, window_days=7: usage))
        monkeypatch.setattr(CloudRunPricing, "memory_gib_second",
                            classmethod(lambda cls: memory_rate))
        monkeypatch.setattr(CloudRunPricing, "status",
                            classmethod(lambda cls: {"memory_gib_second_usd": memory_rate}))
        return FinOpsAgent.audit_spending_and_waste()
    return run


# ------------------------------------------------------------ measurement

def test_a_service_with_no_observations_is_unmeasured_not_idle(audit):
    """Absence of evidence would otherwise be the most confident
    recommendation the agent could make, and the least justified."""
    result = audit(_services(_svc("quiet-service")), usage={})

    assert result["waste_detected_count"] == 0
    assert result["measurement"]["services_unmeasured"] == ["quiet-service"]
    assert result["suggested_action"] is None


def test_a_finding_carries_the_evidence_it_rests_on(audit):
    result = audit(
        _services(_svc("syntrueno", memory="1Gi")),
        usage={"syntrueno": {"memory_peak": 0.15, "samples": 25}},
    )

    finding = result["waste_details"][0]
    assert finding["configured_memory_mib"] == 1024
    # 0.15 * 1024 = 153.6, reported as a whole mebibyte.
    assert finding["observed_peak_memory_mib"] == 154
    assert finding["samples"] == 25
    assert finding["window_days"] == 7


# --------------------------------------------------------------- headroom

def test_the_recommendation_sits_above_the_peak_never_on_it(audit):
    """This project exists because a service died at 512Mi. An agent that
    trims to the high-water mark reintroduces that incident while reporting
    a saving for it."""
    result = audit(
        _services(_svc("syntrueno", memory="1Gi")),
        usage={"syntrueno": {"memory_peak": 0.30, "samples": 40}},
    )

    finding = result["waste_details"][0]
    peak = finding["observed_peak_memory_mib"]
    assert finding["recommended_memory_mib"] > peak
    assert finding["recommended_memory_mib"] == int(peak * HEADROOM_MULTIPLIER)


def test_a_tiny_service_is_not_recommended_below_the_floor(audit):
    result = audit(
        _services(_svc("tiny", memory="1Gi")),
        usage={"tiny": {"memory_peak": 0.001, "samples": 12}},
    )

    assert result["waste_details"][0]["recommended_memory_mib"] == 256


def test_a_marginal_gap_is_not_worth_reporting(audit):
    """A change to a running service needs to be worth making."""
    result = audit(
        _services(_svc("snug", memory="512Mi")),
        usage={"snug": {"memory_peak": 0.60, "samples": 30}},
    )

    assert result["waste_detected_count"] == 0


# ---------------------------------------------------------------- pricing

def test_findings_survive_an_unreachable_price_list(audit):
    """A finding without a price is still a true finding."""
    result = audit(
        _services(_svc("syntrueno", memory="1Gi")),
        usage={"syntrueno": {"memory_peak": 0.15, "samples": 25}},
        memory_rate=None,
    )

    finding = result["waste_details"][0]
    assert finding["recoverable_memory_mib"] > 0
    assert finding["monthly_cost_usd"] is None
    assert result["total_monthly_savings_usd"] == 0.0


def test_no_monthly_figure_is_claimed_for_a_scale_to_zero_service(audit):
    """Billed per request, so a figure derived from always-on seconds would
    overstate it by however much of the month the service was idle."""
    result = audit(
        _services(_svc("canary", memory="1Gi", min_instances=0)),
        usage={"canary": {"memory_peak": 0.15, "samples": 25}},
    )

    finding = result["waste_details"][0]
    assert finding["monthly_cost_usd"] is None
    assert "cost_note" in finding


def test_a_priced_finding_is_the_rate_times_what_is_recoverable(audit):
    result = audit(
        _services(_svc("syntrueno", memory="1Gi", min_instances=1)),
        usage={"syntrueno": {"memory_peak": 0.15, "samples": 25}},
        memory_rate=0.0000025,
    )

    finding = result["waste_details"][0]
    expected = (finding["recoverable_memory_mib"] / 1024) * 30 * 24 * 3600 * 0.0000025
    assert finding["monthly_cost_usd"] == pytest.approx(expected, rel=1e-6)


# --------------------------------------------------------------- proposal

def test_the_proposal_targets_the_largest_finding_and_is_gated(audit):
    result = audit(
        _services(_svc("small", memory="512Mi"), _svc("large", memory="4Gi")),
        usage={"small": {"memory_peak": 0.10, "samples": 20},
               "large": {"memory_peak": 0.05, "samples": 20}},
    )

    action = result["suggested_action"]
    assert action.parameters["service_id"] == "large"
    # Resizing a service that is serving traffic is a person's decision, and
    # the memory limit is the exact setting this system was built to catch.
    assert action.tier.value.startswith("TIER_3")
    assert "peaked at" in action.rationale


def test_no_findings_means_no_proposal(audit):
    assert audit(_services(), usage={})["suggested_action"] is None


# ---------------------------------------------------------------- parsing

@pytest.mark.parametrize("value,expected", [
    ("512Mi", 512), ("1Gi", 1024), ("2Gi", 2048),
    ("1024M", 1024), ("1G", 1000), (None, None), ("nonsense", None),
])
def test_memory_limits_are_parsed_in_the_units_cloud_run_uses(value, expected):
    assert _parse_memory_mib(value) == expected


def test_the_proposal_is_reproducible_when_findings_tie(audit):
    """Two services can recover the same memory. max() would then break the
    tie on whatever order Cloud Run returned them in, and the same project
    would propose a different service run to run."""
    forward = _services(_svc("a-service", memory="1Gi"), _svc("z-service", memory="1Gi"))
    reverse = _services(_svc("z-service", memory="1Gi"), _svc("a-service", memory="1Gi"))
    usage = {"a-service": {"memory_peak": 0.10, "samples": 20},
             "z-service": {"memory_peak": 0.10, "samples": 20}}

    first = audit(forward, usage)["suggested_action"]
    second = audit(reverse, usage)["suggested_action"]

    assert first.parameters["service_id"] == second.parameters["service_id"]


def test_a_priced_finding_outranks_an_equal_unpriced_one(audit):
    """A known dollar figure is a stronger claim than the same amount of
    memory whose cost is unknown."""
    result = audit(
        _services(_svc("always-on", memory="1Gi", min_instances=1),
                  _svc("scale-to-zero", memory="1Gi", min_instances=0)),
        usage={"always-on": {"memory_peak": 0.10, "samples": 20},
               "scale-to-zero": {"memory_peak": 0.10, "samples": 20}},
    )

    assert result["suggested_action"].parameters["service_id"] == "always-on"


def test_the_peak_is_the_same_number_everywhere_it_appears(audit):
    """A card read "peaked at 160Mi" and "peak 159Mi plus 60% headroom" about
    one measurement, because the field was rounded to a decimal and the
    sentence formatted the raw float. On a system whose claim is that every
    number is measured, two answers to the same question is the whole problem
    in miniature."""
    # 0.1558... * 1024 = 159.5x -- the exact shape that used to disagree.
    result = audit(
        _services(_svc("syntrueno", memory="1Gi")),
        usage={"syntrueno": {"memory_peak": 0.15576171875, "samples": 700}},
    )

    finding = result["waste_details"][0]
    peak = finding["observed_peak_memory_mib"]

    assert isinstance(peak, int)
    assert f"peak {peak}Mi" in finding["remediation"]
    assert f"peaked at {peak}Mi" in result["suggested_action"].rationale
