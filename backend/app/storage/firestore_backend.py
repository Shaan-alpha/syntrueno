"""Firestore access layer.

The stores above this module were process-local class attributes, so on Cloud
Run with ``--min-instances 0`` every scale-down wiped the audit ledger, the
memory bank, the registry, and every compiled skill. The live service reported
``audit_ledger_size: 0`` on each cold start while the documentation claimed
persistent cross-session memory.

This module is the only place that talks to Firestore. It follows the same rule
as the Gemini client: **it never raises to its callers.** When Firestore is
disabled or unreachable, ``collection()`` returns ``None`` and each store falls
back to its in-memory path, flagging that it degraded rather than pretending
the write landed.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class FirestoreBackend:
    """Lazily-initialised Firestore client with a hard no-raise contract."""

    _client: Any = None
    _init_attempted: bool = False
    _last_error: Optional[str] = None

    @classmethod
    def _init(cls) -> Any:
        if cls._init_attempted:
            return cls._client
        cls._init_attempted = True

        if not settings.FIRESTORE_ENABLED:
            cls._last_error = "firestore_disabled"
            return None

        try:
            from google.cloud import firestore

            cls._client = firestore.Client(
                project=settings.GOOGLE_CLOUD_PROJECT,
                database=settings.FIRESTORE_DATABASE,
            )
            logger.info(
                "Firestore connected: project=%s database=%s",
                settings.GOOGLE_CLOUD_PROJECT, settings.FIRESTORE_DATABASE,
            )
        except Exception as exc:
            cls._last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
            logger.warning("Firestore unavailable, using in-memory stores: %s", cls._last_error)
            cls._client = None
        return cls._client

    @classmethod
    def available(cls) -> bool:
        return cls._init() is not None

    @classmethod
    def status(cls) -> dict:
        return {
            "enabled": settings.FIRESTORE_ENABLED,
            "connected": cls.available(),
            "database": settings.FIRESTORE_DATABASE,
            "project": settings.GOOGLE_CLOUD_PROJECT,
            "last_error": cls._last_error,
        }

    @classmethod
    def collection(cls, name: str) -> Any:
        """Return a collection reference, or ``None`` when unavailable."""
        client = cls._init()
        if client is None:
            return None
        try:
            return client.collection(name)
        except Exception as exc:
            logger.warning("Firestore collection(%s) failed: %s", name, exc)
            return None

    # ------------------------------------------------------------- helpers

    @classmethod
    def set_document(cls, collection: str, doc_id: str, data: dict) -> bool:
        """Write one document. Returns whether it actually landed."""
        col = cls.collection(collection)
        if col is None:
            return False
        try:
            col.document(doc_id).set(data)
            return True
        except Exception as exc:
            logger.warning("Firestore write %s/%s failed: %s", collection, doc_id, exc)
            return False

    @classmethod
    def get_document(cls, collection: str, doc_id: str) -> Optional[dict]:
        col = cls.collection(collection)
        if col is None:
            return None
        try:
            snap = col.document(doc_id).get()
            return snap.to_dict() if snap.exists else None
        except Exception as exc:
            logger.warning("Firestore read %s/%s failed: %s", collection, doc_id, exc)
            return None

    @classmethod
    def query(
        cls,
        collection: str,
        order_by: Optional[str] = None,
        descending: bool = False,
        limit: Optional[int] = None,
    ) -> Optional[list]:
        """Return documents, or ``None`` when Firestore is unavailable.

        ``None`` and ``[]`` mean different things here and callers depend on
        the distinction: ``None`` is "could not read", ``[]`` is "read fine,
        nothing there".
        """
        col = cls.collection(collection)
        if col is None:
            return None
        try:
            q = col
            if order_by:
                from google.cloud import firestore as fs

                direction = fs.Query.DESCENDING if descending else fs.Query.ASCENDING
                q = q.order_by(order_by, direction=direction)
            if limit:
                q = q.limit(limit)
            return [d.to_dict() for d in q.stream()]
        except Exception as exc:
            logger.warning("Firestore query on %s failed: %s", collection, exc)
            return None

    @classmethod
    def reset(cls) -> None:
        """Test helper: force re-initialisation."""
        cls._client = None
        cls._init_attempted = False
        cls._last_error = None
