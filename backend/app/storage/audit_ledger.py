"""Tamper-evident audit ledger with SHA-256 hash chaining.

Each entry commits to the one before it: ``H(prev_hash || entry)``. Altering a
past entry invalidates every hash after it, so tampering is detectable by
replaying the chain.

The chaining logic was already correct; what was missing was durability. The
ledger lived in a class-level list, so Cloud Run's scale-to-zero discarded the
entire chain on every cold start and the running service reported
``audit_ledger_size: 0`` while claiming an immutable ledger.

The chain head is now recovered from Firestore on first use, so a new container
continues the existing chain rather than starting a fresh one from the genesis
hash.
"""

from __future__ import annotations

import hashlib
import threading
import json
import logging
from typing import Any, Dict, List, Optional

from app.models import AuditLogEntry
from app.storage.firestore_backend import FirestoreBackend

logger = logging.getLogger(__name__)

COLLECTION = "audit_ledger"
GENESIS_HASH = "0" * 64


class AuditLedger:
    """Append-only ledger, Firestore-backed with an in-memory fallback."""

    _memory: List[Dict[str, Any]] = []
    _latest_hash: str = GENESIS_HASH
    _sequence: int = 0
    _head_loaded: bool = False

    # Appending is a read-modify-write over _latest_hash and _sequence. FastAPI
    # runs sync endpoints in a threadpool, so two incidents arriving together
    # can interleave inside a single container: both read the same head, both
    # claim the same sequence, and the chain forks. The window is small and the
    # failure is silent -- verify() would report a broken chain long after the
    # run that broke it. Serialising the append closes it.
    #
    # This lock is per-process. Chain integrity ACROSS containers is what pins
    # the deployment to --max-instances 1; see deploy.sh.
    #
    # Re-entrant because _load_head() guards itself and record_entry() calls it
    # while already holding this. A plain Lock deadlocks on that path.
    _append_lock = threading.RLock()

    # ------------------------------------------------------------- chaining

    @staticmethod
    def _hash_entry(prev_hash: str, payload: Dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(f"{prev_hash}:{canonical}".encode()).hexdigest()

    @classmethod
    def _load_head(cls) -> None:
        """Recover the chain head so a cold container extends the chain.

        Without this, every scale-to-zero would silently fork the ledger into a
        second chain starting at the genesis hash.
        """
        with cls._append_lock:
            if cls._head_loaded:
                return

            rows = FirestoreBackend.query(
                COLLECTION, order_by="sequence", descending=True, limit=1
            )
            # None is "could not read", [] is "read fine, nothing there". Only
            # the second settles the question. Marking the head loaded before
            # the query meant one transient error pinned the container to
            # genesis for its whole life, and the next append forked the chain
            # behind a ledger that already had entries.
            if rows is None:
                logger.warning(
                    "Audit ledger head unread; will retry before the next append"
                )
                return

            cls._head_loaded = True
            if rows:
                head = rows[0]
                cls._latest_hash = head.get("chain_hash", GENESIS_HASH)
                cls._sequence = int(head.get("sequence", 0))
                logger.info(
                    "Audit ledger head recovered at sequence %d", cls._sequence
                )

    # -------------------------------------------------------------- writing

    @classmethod
    def record_entry(cls, entry: AuditLogEntry) -> str:
        with cls._append_lock:
            cls._load_head()

            payload = entry.model_dump()
            cls._sequence += 1
            payload["sequence"] = cls._sequence

            chain_hash = cls._hash_entry(cls._latest_hash, payload)
            record = {
                **payload,
                "prev_hash": cls._latest_hash,
                "chain_hash": chain_hash,
            }

            persisted = FirestoreBackend.set_document(
                COLLECTION, f"{cls._sequence:012d}-{entry.event_id}", record
            )
            # Mirrored either way: the chain must stay continuous in this
            # container even when the write did not land.
            record["persisted"] = persisted
            cls._memory.append(record)

            cls._latest_hash = chain_hash
            return chain_hash

    # -------------------------------------------------------------- reading

    @classmethod
    def get_all_entries(cls) -> List[Dict[str, Any]]:
        rows = FirestoreBackend.query(COLLECTION, order_by="sequence")
        if rows is not None:
            return rows
        return list(cls._memory)

    @classmethod
    def verify_integrity(cls) -> bool:
        """Replay the chain and confirm every link still matches."""
        entries = cls.get_all_entries()
        current = GENESIS_HASH

        for item in entries:
            stored = item.get("chain_hash")
            payload = {
                k: v for k, v in item.items()
                if k not in ("chain_hash", "prev_hash", "persisted")
            }
            if cls._hash_entry(current, payload) != stored:
                logger.error(
                    "Audit chain broken at sequence %s", item.get("sequence")
                )
                return False
            current = stored
        return True

    @classmethod
    def status(cls) -> Dict[str, Any]:
        # Recover first. Reporting the process-local head without this made a
        # container that had not yet appended advertise sequence 0 and a
        # genesis head_hash beside a 26-entry ledger -- on the one endpoint
        # whose job is to say the chain is intact. Seen live 2026-08-26.
        cls._load_head()
        return {
            "entries": len(cls.get_all_entries()),
            "head_hash": cls._latest_hash,
            "sequence": cls._sequence,
            # available() only says a client was built. During the 400
            # "Invalid database id" outage this reported persistent=true
            # while every entry was memory-only.
            "persistent": FirestoreBackend.healthy(),
        }

    @classmethod
    def clear(cls) -> None:
        """Test helper. Does not touch Firestore."""
        cls._memory.clear()
        cls._latest_hash = GENESIS_HASH
        cls._sequence = 0
        cls._head_loaded = False
