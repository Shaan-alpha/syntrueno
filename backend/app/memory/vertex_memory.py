"""Vertex AI Memory Bank, over REST.

Deliberately not the Python SDK. ``google-cloud-aiplatform`` requires protobuf
6.33.6 and this service runs 7.36.0 -- a major-version downgrade sitting
directly underneath ``google-cloud-firestore``, ``grpcio`` and ``google-genai``.
This codebase has already been broken once by a transitive dependency in that
layer: ``google-api-core`` 2.35.0 URL-encoded the Firestore database id and
every read and write failed while the client still constructed cleanly, which
is why requirements.txt pins below it. A convenience wrapper is not worth
re-running that experiment. ``httpx`` and ``google.auth`` are already here.

Why Memory Bank at all, when Firestore already stores incident history: recall
here matches on **meaning**. Measured 2026-08-26 against this project, the query
"container keeps running out of memory and restarting" returned a stored fact
about an OOMKill at distance 0.841 while sharing almost no literal words with
it. The Firestore path is a substring match on the service name and cannot do
that. It remains the fallback because it is always there.

Same hard contract as the Gemini client: **it never raises to its callers.** A
recall failure must cost a recall, not an incident.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


@dataclass
class MemoryRecall:
    """Outcome of one recall. Never an exception."""

    ok: bool
    memories: List[Dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0
    degraded_reason: Optional[str] = None


class VertexMemory:
    """Thin REST client for Agent Engine Memory Bank."""

    _creds: Any = None

    @classmethod
    def reset(cls) -> None:
        """Test helper, and the hook conftest uses to keep the suite offline."""
        cls._creds = None

    @classmethod
    def available(cls) -> bool:
        """Whether a call could succeed. Absent config is not an error."""
        return bool(settings.VERTEX_MEMORY_ENABLED and settings.AGENT_ENGINE_ID)

    @classmethod
    def _base(cls) -> str:
        # AGENT_ENGINE_LOCATION, never VERTEX_LOCATION. The latter is "global"
        # because that is the only place Gemini 3.x is served; reasoningEngines
        # return 404 there. See the comment in config.py.
        loc = settings.AGENT_ENGINE_LOCATION
        return (
            f"https://{loc}-aiplatform.googleapis.com/v1beta1/projects/"
            f"{settings.GOOGLE_CLOUD_PROJECT}/locations/{loc}/reasoningEngines/"
            f"{settings.AGENT_ENGINE_ID}"
        )

    @classmethod
    def _token(cls) -> str:
        """An ADC access token, refreshed when stale.

        Imported lazily so that a deployment without credentials fails at the
        call rather than at import, and so the test suite can stub this without
        triggering credential discovery.
        """
        import google.auth
        import google.auth.transport.requests

        if cls._creds is None:
            cls._creds, _ = google.auth.default(scopes=SCOPES)
        if not cls._creds.valid:
            cls._creds.refresh(google.auth.transport.requests.Request())
        return cls._creds.token

    # --------------------------------------------------------------- writing

    @classmethod
    def record(cls, fact: str, scope: Dict[str, str]) -> bool:
        """Write one fact. Returns whether it actually landed.

        Returning a bool rather than raising keeps the caller's own write to
        Firestore authoritative: the structured record is the source of truth
        and this is the searchable copy.
        """
        if not cls.available():
            return False
        try:
            response = httpx.post(
                f"{cls._base()}/memories",
                headers={"Authorization": f"Bearer {cls._token()}"},
                json={"fact": fact, "scope": scope},
                timeout=settings.VERTEX_MEMORY_TIMEOUT_SECONDS,
            )
            if response.status_code >= 300:
                logger.warning(
                    "Memory Bank write returned %s", response.status_code
                )
                return False
            return True
        except Exception as exc:
            logger.warning("Memory Bank write failed: %s", exc)
            return False

    # --------------------------------------------------------------- reading

    @classmethod
    def recall(
        cls, scope: Dict[str, str], query: str, limit: int = 3
    ) -> MemoryRecall:
        """Semantically recall prior facts for this scope.

        ``query`` is the incident's own error text. Passing it is the whole
        point of the call -- scope alone returns everything for the service in
        insertion order, which Firestore already does for free.
        """
        if not cls.available():
            return MemoryRecall(ok=False, degraded_reason="memory_bank_disabled")

        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{cls._base()}/memories:retrieve",
                headers={"Authorization": f"Bearer {cls._token()}"},
                json={
                    "scope": scope,
                    "similaritySearchParams": {
                        "searchQuery": query,
                        "topK": limit,
                    },
                },
                timeout=settings.VERTEX_MEMORY_TIMEOUT_SECONDS,
            )
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            if response.status_code >= 300:
                logger.warning(
                    "Memory Bank recall returned %s", response.status_code
                )
                return MemoryRecall(
                    ok=False,
                    latency_ms=elapsed,
                    degraded_reason=f"http_{response.status_code}",
                )
            payload = response.json()
        except Exception as exc:
            return MemoryRecall(
                ok=False,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                degraded_reason=f"{type(exc).__name__}: {str(exc)[:120]}",
            )

        memories = [
            {
                "fact": row.get("memory", {}).get("fact", ""),
                "scope": row.get("memory", {}).get("scope", {}),
                "distance": row.get("distance"),
                "recorded_at": row.get("memory", {}).get("createTime"),
            }
            for row in payload.get("retrievedMemories", [])
        ]
        return MemoryRecall(
            ok=True,
            memories=memories,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    @classmethod
    def status(cls) -> Dict[str, Any]:
        """What this layer is, for /api/v1/status."""
        return {
            "enabled": settings.VERTEX_MEMORY_ENABLED,
            "engine_id": settings.AGENT_ENGINE_ID or None,
            "location": settings.AGENT_ENGINE_LOCATION,
        }
