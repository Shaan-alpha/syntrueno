"""Incident memory across sessions.

The previous implementation held a class-level dict whose write methods —
``record_incident_resolution`` and ``update_org_profile`` — were never called
from anywhere in the codebase. The store was read-only in practice, so the
claim that the swarm "remembers past incidents and adapts across sessions" had
no mechanism behind it: it could not learn anything, because nothing ever wrote.

Writes go to Firestore so they survive scale-to-zero, and the commander now
actually records each resolution, so the next incident on the same service
genuinely sees what happened last time.

``update_org_profile`` was never wired up. It sat here alongside a
``DEFAULT_PROFILE`` of invented facts about a fictional company — a budget, a
pool size, an instance cap — that no agent read and no endpoint served, which
made this module look like it held organisational context the swarm reasoned
over. It did not, so it is gone rather than left as furniture.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from app.memory.vertex_memory import VertexMemory
from app.storage.firestore_backend import FirestoreBackend

INCIDENT_COLLECTION = "incident_history"


class MemoryBank:
    """Cross-session incident memory, Firestore-backed with an in-memory fallback."""

    _incidents: List[Dict[str, Any]] = []

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

        # Written to both stores on purpose. Firestore holds the structured
        # record -- scores, tiers, ids, the things the console renders. Memory
        # Bank holds a sentence, because what it does with it is semantic
        # search, and a dict of fields is not something you can search by
        # meaning. Neither is a cache of the other.
        record["memory_bank"] = VertexMemory.record(
            fact=(
                f"{service} incident: {root_cause} "
                f"Resolution: {resolution} "
                f"Judge scored {judge_score} and routed it to {tier}."
            ),
            scope={"service_id": service},
        )

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
        # Nothing matched means nothing is known about this service, and the
        # honest answer is an empty list. This used to fall back to
        # ``history[:limit]`` -- the most recent incidents from *other*
        # services -- which the Commander then reported as "N prior incident(s)
        # on this service" and handed to the SRE agent as context. A first
        # incident on a new service arrived carrying someone else's history,
        # described as its own.
        return matches[:limit]

    @classmethod
    def recall_for_incident(
        cls, service: str, query: str, limit: int = 3
    ) -> Tuple[List[Dict[str, Any]], str]:
        """Prior incidents for this service, and which store answered.

        Memory Bank matches on meaning, so an alert worded nothing like the
        stored fact still recalls it -- measured at distance 0.841 for a query
        sharing almost no literal words. The Firestore path is a substring
        match and cannot do that, but it is the fallback because it is always
        there.

        The source is returned rather than logged. A recall that quietly
        degraded would look identical to one that worked, and this project's
        whole claim is that it does not do that.
        """
        recall = VertexMemory.recall({"service_id": service}, query, limit)

        # `ok` with no rows is not an answer worth keeping while Firestore
        # holds history: a newly-created memory bank would otherwise erase
        # recall entirely on its first run.
        if recall.ok and recall.memories:
            return (
                [
                    {
                        "root_cause": m["fact"],
                        "service": service,
                        "distance": m.get("distance"),
                        "resolved_at": m.get("recorded_at"),
                    }
                    for m in recall.memories
                ],
                "memory_bank",
            )
        return cls.query_similar_incidents(service, limit=limit), "firestore"

    @classmethod
    def status(cls) -> Dict[str, Any]:
        rows = FirestoreBackend.query(INCIDENT_COLLECTION, limit=100)
        return {
            "persistent": FirestoreBackend.healthy(),
            "incidents_recorded": len(rows) if rows is not None else len(cls._incidents),
        }

    @classmethod
    def clear(cls) -> None:
        """Test helper. Does not touch Firestore."""
        cls._incidents.clear()
