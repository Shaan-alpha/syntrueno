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
from typing import Any, Dict, List, Optional

from app.storage.firestore_backend import FirestoreBackend

COLLECTION = "trajectories"


class TrajectoryRecorder:
    """Append-only log of executed tool sequences."""

    _memory: List[Dict[str, Any]] = []

    @classmethod
    def record_from_result(
        cls, incident_type: str, result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Record the trajectory described by a finished swarm result.

        Every caller was pulling the same four fields out of ``result`` by
        hand, and the compiler needs three more than that. Reading them in one
        place keeps the triage, stream and event-ingest paths from drifting
        into recording different things about the same run.
        """
        judge = result.get("judge_evaluation") or {}
        telemetry = result.get("telemetry") or {}
        sre = telemetry.get("sre") or {}

        return cls.record_trajectory(
            incident_type=incident_type,
            tool_sequence=result.get("executed_tools", []),
            parameters=(result.get("proposed_action") or {}).get("parameters", {}),
            duration_ms=result.get("total_duration_ms", 0.0),
            incident_id=result.get("incident_id"),
            judge_score=judge.get("score"),
            judge_approved=judge.get("is_approved"),
            diagnosis_tokens=sre.get("total_tokens"),
        )

    @classmethod
    def record_trajectory(
        cls,
        incident_type: str,
        tool_sequence: List[str],
        parameters: Dict[str, Any],
        duration_ms: float,
        incident_id: Optional[str] = None,
        judge_score: Optional[float] = None,
        judge_approved: Optional[bool] = None,
        diagnosis_tokens: Optional[int] = None,
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
            # The compiler needs these three to say anything true about a
            # skill it mines: which incident this was (so two recordings of
            # one incident cannot look like a recurring pattern), whether the
            # Judge approved it, and what the diagnosis call actually cost --
            # which is the only number a compiled skill can honestly claim to
            # save.
            "incident_id": incident_id,
            "judge_score": judge_score,
            "judge_approved": judge_approved,
            "diagnosis_tokens": diagnosis_tokens,
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
