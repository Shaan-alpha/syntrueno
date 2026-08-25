"""Cloud Run rates, fetched from Google's own price list.

The FinOps agent has to turn "this service is holding 1Gi it never touches"
into a number, and that number is only worth showing if it came from somewhere
real. Hardcoding a rate makes the whole finding a guess wearing a dollar sign,
and rates change.

So the rate comes from the Cloud Billing Catalog API, for the configured
region, at request time. When the catalog is unreachable this returns ``None``
and the agent reports its findings without prices, because a finding with no
price is still a true finding and a made-up price is not.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Cloud Run's service id in the billing catalog. Stable, and the catalog is
# keyed by it rather than by name.
CLOUD_RUN_SERVICE_ID = "152E-C115-5142"
CATALOG_URL = "https://cloudbilling.googleapis.com/v1/services/{service}/skus"


class CloudRunPricing:
    """Published Cloud Run rates for the deployment's region."""

    _rates: Optional[Dict[str, float]] = None
    _last_error: Optional[str] = None

    @classmethod
    def reset(cls) -> None:
        cls._rates = None
        cls._last_error = None

    @classmethod
    def memory_gib_second(cls) -> Optional[float]:
        """USD per GiB-second of provisioned memory, or None if unknown."""
        return (cls._load() or {}).get("memory_gib_second")

    @classmethod
    def cpu_second(cls) -> Optional[float]:
        """USD per vCPU-second, or None if unknown."""
        return (cls._load() or {}).get("cpu_second")

    @classmethod
    def status(cls) -> Dict[str, Any]:
        rates = cls._load() or {}
        return {
            "source": "cloudbilling.googleapis.com catalog",
            "region": settings.GOOGLE_CLOUD_LOCATION,
            "memory_gib_second_usd": rates.get("memory_gib_second"),
            "cpu_second_usd": rates.get("cpu_second"),
            "last_error": cls._last_error,
        }

    # ------------------------------------------------------------ internals

    @classmethod
    def _load(cls) -> Optional[Dict[str, float]]:
        if cls._rates is not None:
            return cls._rates
        if settings.SIMULATION_MODE:
            cls._last_error = "simulation_mode"
            return None

        try:
            import google.auth
            import httpx
            from google.auth.transport.requests import Request

            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            credentials.refresh(Request())

            rates: Dict[str, float] = {}
            page_token = None
            # The catalog is paginated and Cloud Run has several hundred SKUs
            # across every region and accelerator. Stop as soon as both rates
            # for this region have been seen.
            for _ in range(10):
                response = httpx.get(
                    CATALOG_URL.format(service=CLOUD_RUN_SERVICE_ID),
                    params={
                        "pageSize": 200,
                        **({"pageToken": page_token} if page_token else {}),
                    },
                    headers={
                        "Authorization": f"Bearer {credentials.token}",
                        "x-goog-user-project": settings.GOOGLE_CLOUD_PROJECT,
                    },
                    timeout=15.0,
                )
                response.raise_for_status()
                payload = response.json()

                for sku in payload.get("skus", []):
                    cls._absorb(sku, rates)

                if len(rates) == 2:
                    break
                page_token = payload.get("nextPageToken")
                if not page_token:
                    break

            if not rates:
                cls._last_error = "no_matching_sku"
                return None

            cls._rates = rates
            cls._last_error = None
            logger.info("Cloud Run rates loaded for %s: %s",
                        settings.GOOGLE_CLOUD_LOCATION, rates)
            return rates

        except Exception as exc:
            cls._last_error = f"{type(exc).__name__}: {str(exc)[:140]}"
            logger.warning("Cloud Run pricing unavailable: %s", cls._last_error)
            return None

    @classmethod
    def _absorb(cls, sku: Dict[str, Any], rates: Dict[str, float]) -> None:
        """Take a SKU's rate if it is one of the two this module cares about."""
        if settings.GOOGLE_CLOUD_LOCATION not in (sku.get("serviceRegions") or []):
            return

        description = sku.get("description", "")
        # GPU and Jobs SKUs quote per-second rates in the same units as the
        # ones wanted here, so matching on units alone picks up the wrong row.
        if "GPU" in description or description.startswith("Jobs"):
            return

        pricing = (sku.get("pricingInfo") or [{}])[0]
        expression = pricing.get("pricingExpression") or {}
        tiers = expression.get("tieredRates") or []
        if not tiers:
            return

        unit_price = tiers[-1].get("unitPrice") or {}
        rate = int(unit_price.get("units", 0)) + unit_price.get("nanos", 0) / 1e9
        if rate <= 0:
            return

        unit = expression.get("usageUnit")
        if unit == "GiBy.s" and "Memory" in description:
            rates.setdefault("memory_gib_second", rate)
        elif unit == "s" and "CPU" in description:
            rates.setdefault("cpu_second", rate)
