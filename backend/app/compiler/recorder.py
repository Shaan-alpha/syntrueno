"""Records the tool sequences the swarm actually executed.

This feeds the ThorForja compiler. Previously the API handed it a hardcoded
sequence — the same three tool names on every incident regardless of what the
agents did — so the "trajectory mining" was rediscovering a pattern the caller
had planted one line earlier. It now records what genuinely ran, with measured
durations, persisted so patterns can accumulate across container lifetimes
rather than resetting on every cold start.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.storage.firestore_backend import FirestoreBackend

COLLECTION = "trajectories"


class TrajectoryRecorder:
    """Append-only log of executed tool sequences."""

    _memory: List[Dict[str, Any]] = []

    @classmethod
    def record_trajectory(
        cls,
        incident_type: str,
        tool_sequence: List[str],
        parameters: Dict[str, Any],
        duration_ms: float,
    ) -> Dict[str, Any]:
        if not tool_sequence:
            # Nothing ran, so there is no trajectory to learn from.
            return {}

        signature = "->".join(tool_sequence)
        recorded_at = datetime.now(timezone.utc).isoformat()
        doc_id = hashlib.sha256(
            f"{signature}:{recorded_at}".encode()
        ).hexdigest()[:24]

        entry = {
            "trajectory_id": doc_id,
            "incident_type": incident_type,
            "tool_sequence": tool_sequence,
            "skeleton_signature": signature,
            "parameters": parameters,
            "duration_ms": duration_ms,
            "recorded_at": recorded_at,
        }
        entry["persisted"] = FirestoreBackend.set_document(COLLECTION, doc_id, entry)
        cls._memory.append(entry)
        return entry

    @classmethod
    def get_all_trajectories(cls) -> List[Dict[str, Any]]:
        rows = FirestoreBackend.query(
            COLLECTION, order_by="recorded_at", descending=True, limit=200
        )
        return rows if rows is not None else list(cls._memory)

    @classmethod
    def status(cls) -> Dict[str, Any]:
        return {
            "recorded": len(cls.get_all_trajectories()),
            "persistent": FirestoreBackend.healthy(),
        }

    @classmethod
    def clear(cls) -> None:
        """Test helper. Does not touch Firestore."""
        cls._memory.clear()
