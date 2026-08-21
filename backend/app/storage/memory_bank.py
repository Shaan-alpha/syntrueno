"""Organisational memory across sessions.

The previous implementation held a class-level dict whose write methods —
``record_incident_resolution`` and ``update_org_profile`` — were never called
from anywhere in the codebase. The store was read-only in practice, so the
claim that the swarm "remembers past incidents and adapts across sessions" had
no mechanism behind it: it could not learn anything, because nothing ever wrote.

Two things change here. Writes go to Firestore so they survive scale-to-zero,
and the commander now actually records each resolution, so the next incident on
the same service genuinely sees what happened last time.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.storage.firestore_backend import FirestoreBackend

logger = logging.getLogger(__name__)

PROFILE_COLLECTION = "memory_bank"
PROFILE_DOC = "org_profile"
INCIDENT_COLLECTION = "incident_history"

DEFAULT_PROFILE: Dict[str, Any] = {
    "org_name": "Acme Global Infrastructure",
    "cloud_budget_monthly_usd": 5000.0,
    "primary_region": "us-central1",
    "db_pool_standard": 150,
    "max_cloud_run_instances": 10,
}


class MemoryBank:
    """Cross-session memory, Firestore-backed with an in-memory fallback."""

    _profile: Dict[str, Any] = dict(DEFAULT_PROFILE)
    _incidents: List[Dict[str, Any]] = []

    # -------------------------------------------------------------- profile

    @classmethod
    def get_org_profile(cls) -> Dict[str, Any]:
        stored = FirestoreBackend.get_document(PROFILE_COLLECTION, PROFILE_DOC)
        if stored:
            cls._profile = stored
        return dict(cls._profile)

    @classmethod
    def update_org_profile(cls, updates: Dict[str, Any]) -> Dict[str, Any]:
        profile = cls.get_org_profile()
        profile.update(updates)
        profile["updated_at"] = datetime.now(timezone.utc).isoformat()
        cls._profile = profile
        FirestoreBackend.set_document(PROFILE_COLLECTION, PROFILE_DOC, profile)
        return dict(profile)

    # ------------------------------------------------------------ incidents

    @classmethod
    def record_incident_resolution(
        cls,
        incident_id: str,
        service: str,
        root_cause: str,
        resolution: str,
        judge_score: float | None = None,
        tier: str | None = None,
    ) -> Dict[str, Any]:
        """Persist what happened, so the next incident can learn from it."""
        record = {
            "incident_id": incident_id,
            "service": service,
            "root_cause": root_cause,
            "resolution": resolution,
            "judge_score": judge_score,
            "tier": tier,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }
        persisted = FirestoreBackend.set_document(
            INCIDENT_COLLECTION, incident_id, record
        )
        record["persisted"] = persisted
        cls._incidents.append(record)
        return record

    @classmethod
    def query_similar_incidents(
        cls, service_query: str, limit: int = 3
    ) -> List[Dict[str, Any]]:
        """Prior incidents relevant to this service.

        Firestore has no substring predicate, so the match runs client-side over
        a bounded recent window. At the scale this operates on that is cheaper
        and simpler than maintaining a search index, and it keeps the read
        inside the free tier's daily quota.
        """
        rows = FirestoreBackend.query(
            INCIDENT_COLLECTION, order_by="resolved_at", descending=True, limit=50
        )
        history = rows if rows is not None else list(cls._incidents)

        needle = service_query.lower()
        matches = [
            inc for inc in history
            if needle in str(inc.get("service", "")).lower()
            or needle in str(inc.get("root_cause", "")).lower()
        ]
        return matches[:limit] if matches else history[:limit]

    @classmethod
    def status(cls) -> Dict[str, Any]:
        rows = FirestoreBackend.query(INCIDENT_COLLECTION, limit=100)
        return {
            "persistent": FirestoreBackend.available(),
            "incidents_recorded": len(rows) if rows is not None else len(cls._incidents),
        }

    @classmethod
    def clear(cls) -> None:
        """Test helper. Does not touch Firestore."""
        cls._profile = dict(DEFAULT_PROFILE)
        cls._incidents.clear()
