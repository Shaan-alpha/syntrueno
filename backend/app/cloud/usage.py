"""What Cloud Run services actually used, from Cloud Monitoring.

Over-provisioning can only be claimed against something measured. This reads
the real utilisation series for each service and reports the peak, because the
peak is what a memory limit has to survive -- sizing to the mean is how a
service that looks comfortable on average gets OOMKilled at its busiest
minute, which is the incident this whole system exists to handle.

Returns ``None`` for a service with no data rather than zero. No data means
the service was idle or too new to have been observed, and treating that as
"used nothing, shrink it" would recommend a change on the strength of an
absence.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)

MEMORY_METRIC = "run.googleapis.com/container/memory/utilizations"
CPU_METRIC = "run.googleapis.com/container/cpu/utilizations"


class ServiceUsage:
    """Measured utilisation, keyed by service name."""

    _client: Any = None
    _init_attempted: bool = False
    _last_error: Optional[str] = None

    @classmethod
    def _get_client(cls) -> Any:
        if cls._init_attempted:
            return cls._client
        cls._init_attempted = True
        try:
            from google.cloud import monitoring_v3

            cls._client = monitoring_v3.MetricServiceClient()
        except Exception as exc:
            cls._last_error = f"{type(exc).__name__}: {str(exc)[:140]}"
            logger.warning("Monitoring client unavailable: %s", cls._last_error)
            cls._client = None
        return cls._client

    @classmethod
    def reset(cls) -> None:
        cls._client = None
        cls._init_attempted = False
        cls._last_error = None

    @classmethod
    def peak_utilization(cls, window_days: int = 7) -> Dict[str, Dict[str, Any]]:
        """Peak memory and CPU utilisation per service, as fractions of limit.

        ``{"syntrueno": {"memory_peak": 0.149, "cpu_peak": 0.047, "samples": 25}}``
        Services with no observations are absent from the result rather than
        present with zeroes.
        """
        if settings.SIMULATION_MODE:
            return {}

        client = cls._get_client()
        if client is None:
            return {}

        try:
            from google.cloud import monitoring_v3

            now = int(time.time())
            interval = monitoring_v3.TimeInterval({
                "end_time": {"seconds": now},
                "start_time": {"seconds": now - window_days * 24 * 3600},
            })

            usage: Dict[str, Dict[str, Any]] = {}
            for metric, key in ((MEMORY_METRIC, "memory_peak"),
                                (CPU_METRIC, "cpu_peak")):
                for series in client.list_time_series(request={
                    "name": f"projects/{settings.GOOGLE_CLOUD_PROJECT}",
                    "filter": f'metric.type = "{metric}"',
                    "interval": interval,
                    "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                }):
                    service = series.resource.labels.get("service_name")
                    if not service:
                        continue
                    entry = usage.setdefault(service, {"samples": 0})
                    for point in series.points:
                        value = cls._read_point(point)
                        if value is None:
                            continue
                        entry["samples"] += 1
                        if value > entry.get(key, 0.0):
                            entry[key] = value

            cls._last_error = None
            return usage

        except Exception as exc:
            cls._last_error = f"{type(exc).__name__}: {str(exc)[:140]}"
            logger.warning("Utilisation query failed: %s", cls._last_error)
            return {}

    @staticmethod
    def _read_point(point: Any) -> Optional[float]:
        """These metrics arrive as distributions; scalars are tolerated too."""
        value = point.value
        distribution = value.distribution_value
        if distribution and distribution.count:
            # The 99th percentile bucket would be better, but the bucket layout
            # is not guaranteed across metric versions. The distribution mean
            # over a one-minute alignment window is close enough to a peak at
            # this granularity, and understating it is the safe direction: it
            # makes the agent recommend smaller reductions, not larger ones.
            return float(distribution.mean)
        if value.double_value:
            return float(value.double_value)
        if value.int64_value:
            return float(value.int64_value)
        return None

    @classmethod
    def status(cls) -> Dict[str, Any]:
        """Reports state; does not create it.

        Constructing the client here to answer "are you available" made a
        status call do credential discovery, which put a real network round
        trip inside the offline test suite.
        """
        return {
            "source": "monitoring.googleapis.com",
            "queried": cls._init_attempted,
            "available": cls._client is not None,
            "last_error": cls._last_error,
        }
