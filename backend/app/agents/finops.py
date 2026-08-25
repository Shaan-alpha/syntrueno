"""FinOps agent: finds over-provisioning by measuring it.

This module used to return three invented resources -- an orphaned disk, a dev
API pinned to three instances, an unpartitioned BigQuery table -- none of which
existed in the project, totalling an invented $440/month. Its docstring said it
queried BigQuery billing records. It did not query anything; the numbers were
literals, and the only measured value in the function was how long it took to
build the list.

It now compares each service's configured limits against the utilisation Cloud
Monitoring actually recorded, and prices the gap at the rate Google's own
catalog publishes for the region. Three rules keep it honest:

**A finding needs an observation.** A service Monitoring has no data for is
reported as unmeasured, not as idle. Absence of evidence sized a limit to zero
would be the most confident recommendation this agent could make and the least
justified.

**Headroom is not waste.** The recommendation is peak plus a margin, never the
peak itself. This system exists because a service died at 512Mi; an agent that
trims to the high-water mark reintroduces exactly that incident, and would do
it while reporting a saving.

**No price, no number.** When the catalog is unreachable the findings still
list what is over-provisioned, without dollars. A finding without a price is
still true.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from app.cloud.pricing import CloudRunPricing
from app.cloud.runadmin import CloudRunAdmin
from app.cloud.usage import ServiceUsage
from app.models import ExecutionTier, RemediationAction

logger = logging.getLogger(__name__)

SECONDS_PER_MONTH = 30 * 24 * 3600

# Peak plus 60%, floored at 256Mi. Chosen to sit well clear of the failure this
# project was built around rather than to maximise the reported saving.
HEADROOM_MULTIPLIER = 1.6
MIN_RECOMMENDED_MIB = 256

# Below this there is nothing worth an engineer's attention, let alone a
# change to a running service.
MIN_REPORTABLE_MIB = 128


def _parse_memory_mib(value: Optional[str]) -> Optional[int]:
    """Cloud Run quotes limits as '512Mi', '1Gi', '1024M'."""
    if not value:
        return None
    text = str(value).strip()
    try:
        if text.endswith("Gi"):
            return int(float(text[:-2]) * 1024)
        if text.endswith("Mi"):
            return int(float(text[:-2]))
        if text.endswith("G"):
            return int(float(text[:-1]) * 1000)
        if text.endswith("M"):
            return int(float(text[:-1]))
        return int(float(text)) // (1024 * 1024)
    except ValueError:
        return None


class FinOpsAgent:
    """Audits real Cloud Run configuration against real measured usage."""

    @classmethod
    def audit_spending_and_waste(cls, window_days: int = 7) -> Dict[str, Any]:
        started = time.perf_counter()

        listing = CloudRunAdmin.list_services()
        usage = ServiceUsage.peak_utilization(window_days=window_days)
        memory_rate = CloudRunPricing.memory_gib_second()

        findings: List[Dict[str, Any]] = []
        unmeasured: List[str] = []

        for service in listing.get("services", []):
            name = service["service"]
            configured_mib = _parse_memory_mib(service.get("memory"))
            observed = usage.get(name) or {}
            peak = observed.get("memory_peak")

            if configured_mib is None or peak is None or not observed.get("samples"):
                unmeasured.append(name)
                continue

            peak_mib = peak * configured_mib
            recommended = max(
                MIN_RECOMMENDED_MIB, int(peak_mib * HEADROOM_MULTIPLIER)
            )
            recoverable = configured_mib - recommended
            if recoverable < MIN_REPORTABLE_MIB:
                continue

            finding = {
                "resource_id": f"cloud-run/{name}",
                "resource_type": "Cloud Run Service",
                "configured_memory_mib": configured_mib,
                "observed_peak_memory_mib": round(peak_mib, 1),
                "observed_peak_utilization": round(peak, 4),
                "samples": observed["samples"],
                "window_days": window_days,
                "recommended_memory_mib": recommended,
                "recoverable_memory_mib": recoverable,
                "min_instances": service.get("min_instances", 0),
                "remediation": (
                    f"Reduce memory limit from {configured_mib}Mi to "
                    f"{recommended}Mi (peak {peak_mib:.0f}Mi plus "
                    f"{int((HEADROOM_MULTIPLIER - 1) * 100)}% headroom)"
                ),
                "monthly_cost_usd": None,
            }

            # An instance only costs memory for the time it is running. With
            # min-instances 0 a service is billed per request, and a monthly
            # figure derived from always-on seconds would overstate the saving
            # by whatever fraction of the month it was actually idle.
            min_instances = service.get("min_instances") or 0
            if memory_rate is not None and min_instances > 0:
                gib = recoverable / 1024
                finding["monthly_cost_usd"] = round(
                    gib * SECONDS_PER_MONTH * memory_rate * min_instances, 2
                )
            elif memory_rate is not None:
                finding["cost_note"] = (
                    "scale-to-zero: billed per request, so the saving depends "
                    "on traffic and is not stated as a monthly figure"
                )

            findings.append(finding)

        priced = [f["monthly_cost_usd"] for f in findings
                  if f.get("monthly_cost_usd") is not None]

        result: Dict[str, Any] = {
            "waste_detected_count": len(findings),
            "total_monthly_savings_usd": round(sum(priced), 2) if priced else 0.0,
            "waste_details": findings,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            # Said plainly, because the previous version's confidence was the
            # problem: what was looked at, what could not be, and why.
            "measurement": {
                "services_examined": len(listing.get("services", [])),
                "services_unmeasured": unmeasured,
                "window_days": window_days,
                "cloud_run_available": listing.get("available", False),
                "pricing": CloudRunPricing.status(),
                "monitoring": ServiceUsage.status(),
                "billing_export": {
                    "configured": False,
                    "note": (
                        "No BigQuery billing export exists for this project, so "
                        "these figures are computed from published rates and "
                        "measured utilisation rather than from billed spend."
                    ),
                },
            },
        }

        if not listing.get("available", False):
            result["degraded"] = True
            result["degraded_reason"] = listing.get("reason", "cloud_run_unavailable")

        result["suggested_action"] = cls._suggest(findings)
        return result

    @classmethod
    def _suggest(cls, findings: List[Dict[str, Any]]) -> Optional[RemediationAction]:
        """A proposal for the largest finding, or None when there is nothing.

        Returning None matters: the previous version always produced an action,
        so the console always had something to show whether or not anything was
        wrong. Tier 3 because resizing a service that is serving traffic is a
        decision for a person, and the memory limit is the exact setting whose
        mis-sizing this system was built to catch.
        """
        if not findings:
            return None

        # Ranked, not max()'d. Two findings can recover the same amount of
        # memory, and max() would then break the tie on whatever order Cloud
        # Run happened to return its services in -- so the same project could
        # propose a different service run to run. Priced savings rank first
        # because a known dollar figure is a stronger claim than an equal
        # amount of memory whose cost is unknown; the name is a final
        # tie-break purely to make the choice reproducible.
        target = sorted(
            findings,
            key=lambda f: (
                -(f.get("monthly_cost_usd") or 0.0),
                -f["recoverable_memory_mib"],
                f["resource_id"],
            ),
        )[0]
        service = target["resource_id"].split("/", 1)[1]

        return RemediationAction(
            action_id=f"act-finops-{service}",
            tool_name="update_cloud_run_resources",
            parameters={
                "service_id": service,
                "memory": f"{target['recommended_memory_mib']}Mi",
            },
            rationale=(
                f"{service} is provisioned at {target['configured_memory_mib']}Mi "
                f"and peaked at {target['observed_peak_memory_mib']:.0f}Mi across "
                f"{target['samples']} samples over {target['window_days']} days. "
                f"Recommending {target['recommended_memory_mib']}Mi keeps "
                f"{int((HEADROOM_MULTIPLIER - 1) * 100)}% headroom above the peak."
            ),
            tier=ExecutionTier.TIER_3_HUMAN_GATE,
            estimated_cost_delta_usd=(
                -target["monthly_cost_usd"]
                if target.get("monthly_cost_usd") is not None
                else None
            ),
        )
