"""D17 human-in-the-loop approval gate.

The previous implementation returned a pending record but never stored it, then
let the signing endpoint accept a complete record from the request body. It
recomputed the hash from the caller's own action and compared it against the
caller's own hash — which always matched, because the caller computed both. An
unauthenticated stranger could forge an approval for any action.

This version fixes it structurally rather than by adding a check:

- Pending approvals live **server-side**. The store is the only source of truth.
- Signing takes ``(approval_id, engineer_id)``. The action being approved is
  read from the server's copy and can never be supplied by the caller.
- Execution requires an approval whose ``action_hash`` matches the action about
  to run, so a signature for one action cannot authorise a different one.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app.config import settings
from app.models import ApprovalRecord, RemediationAction
from app.storage.firestore_backend import FirestoreBackend

COLLECTION = "approvals"


class ApprovalNotFound(Exception):
    """No pending approval with that id."""


class ApprovalStateError(Exception):
    """The approval exists but is not in a signable state."""


class HumanApprovalGate:
    """Server-side approval store, backed by Firestore.

    Durability matters here beyond surviving restarts: on Cloud Run with
    scale-to-zero, the request that creates an approval and the request that
    signs it routinely land on different container instances. A purely
    in-process store would make the gate unsignable in production while
    appearing to work locally.
    """

    _pending: Dict[str, ApprovalRecord] = {}

    # --------------------------------------------------------- persistence

    @classmethod
    def _persist(cls, record: ApprovalRecord) -> bool:
        return FirestoreBackend.set_document(
            COLLECTION, record.approval_id, record.model_dump()
        )

    @classmethod
    def _load(cls, approval_id: str) -> Optional[ApprovalRecord]:
        """Fetch from memory, falling back to Firestore.

        A pending approval must outlive the container that created it. On Cloud
        Run with scale-to-zero the request that creates the approval and the
        request that signs it routinely hit different instances, so an
        in-memory-only store would make the gate unsignable in production.
        """
        if approval_id in cls._pending:
            return cls._pending[approval_id]

        stored = FirestoreBackend.get_document(COLLECTION, approval_id)
        if stored is None:
            return None
        try:
            record = ApprovalRecord(**stored)
        except Exception:
            return None
        cls._pending[approval_id] = record
        return record

    # ------------------------------------------------------------- hashing

    @staticmethod
    def compute_action_hash(action: RemediationAction) -> str:
        """Bind a signature to exactly one action and parameter set."""
        payload = {
            "tool_name": action.tool_name,
            "parameters": action.parameters,
            "tier": action.tier.value,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()

    # ------------------------------------------------------------ lifecycle

    @classmethod
    def create_pending_approval(
        cls, incident_id: str, action: RemediationAction
    ) -> ApprovalRecord:
        """Create and **persist** a pending approval."""
        action_hash = cls.compute_action_hash(action)
        record = ApprovalRecord(
            approval_id=f"appr-{secrets.token_hex(8)}",
            incident_id=incident_id,
            action_hash=action_hash,
            requested_action=action,
            status="PENDING",
            expires_at=(
                datetime.now(timezone.utc)
                + timedelta(minutes=settings.APPROVAL_TTL_MINUTES)
            ).isoformat(),
        )
        cls._pending[record.approval_id] = record
        cls._persist(record)
        return record

    @classmethod
    def get(cls, approval_id: str) -> Optional[ApprovalRecord]:
        return cls._load(approval_id)

    @classmethod
    def sign_approval(cls, approval_id: str, engineer_id: str) -> ApprovalRecord:
        """Sign a pending approval by id.

        The caller supplies only which approval to sign and who is signing. The
        action itself comes from the server's stored copy, so there is nothing
        for a caller to forge.
        """
        record = cls._load(approval_id)
        if record is None:
            raise ApprovalNotFound(
                f"No pending approval {approval_id!r}. Approvals must be created "
                f"by the swarm before they can be signed."
            )
        if record.status != "PENDING":
            raise ApprovalStateError(
                f"Approval {approval_id!r} is already {record.status}."
            )

        # Defence in depth: the stored action must still hash to the stored
        # hash. Catches tampering with the store itself.
        if cls.compute_action_hash(record.requested_action) != record.action_hash:
            raise ApprovalStateError(
                f"Integrity failure on {approval_id!r}: stored action does not "
                f"match its recorded hash."
            )

        record.status = "APPROVED"
        record.signed_by = engineer_id
        record.signed_at = datetime.now(timezone.utc).isoformat()
        cls._persist(record)
        return record

    @classmethod
    def reject_approval(cls, approval_id: str, engineer_id: str) -> ApprovalRecord:
        record = cls._load(approval_id)
        if record is None:
            raise ApprovalNotFound(f"No pending approval {approval_id!r}.")
        record.status = "REJECTED"
        record.signed_by = engineer_id
        record.signed_at = datetime.now(timezone.utc).isoformat()
        cls._persist(record)
        return record

    # ----------------------------------------------------- execution check

    @classmethod
    def authorises(
        cls, action: RemediationAction, approval_id: Optional[str] = None
    ) -> bool:
        """True when an unspent signature authorises exactly this action.

        Pass ``approval_id`` to bind the check to one specific signature. Doing
        so matters: several signed-but-unexecuted approvals for the same action
        can coexist (a run that failed after signing leaves one behind), and
        without binding, a replay would silently satisfy itself from a
        different signature in that pool. Observed exactly that way in testing.
        """
        return cls._find_authorisation(action, approval_id) is not None

    @classmethod
    def _find_authorisation(
        cls, action: RemediationAction, approval_id: Optional[str] = None
    ) -> Optional[ApprovalRecord]:
        """The unspent, unexpired signature covering this exact action."""
        target = cls.compute_action_hash(action)
        now = datetime.now(timezone.utc)

        if approval_id is not None:
            record = cls._load(approval_id)
            candidates = [record] if record else []
        else:
            candidates = cls.list_all()

        for record in candidates:
            if record.status != "APPROVED" or record.action_hash != target:
                continue
            if record.consumed_at is not None:
                continue  # already spent on an execution
            if record.expires_at:
                try:
                    if datetime.fromisoformat(record.expires_at) < now:
                        continue  # signature has aged out
                except ValueError:
                    pass
            return record
        return None

    @classmethod
    def consume(
        cls, action: RemediationAction, approval_id: Optional[str] = None
    ) -> Optional[ApprovalRecord]:
        """Spend the signature authorising this action.

        Called immediately after a mutation lands, so the same signature can
        never authorise a second execution.
        """
        record = cls._find_authorisation(action, approval_id)
        if record is None:
            return None
        record.consumed_at = datetime.now(timezone.utc).isoformat()
        record.consumed_by_action_id = action.action_id
        cls._pending[record.approval_id] = record
        cls._persist(record)
        return record

    # ---------------------------------------------------------- inspection

    @classmethod
    def list_all(cls) -> List[ApprovalRecord]:
        rows = FirestoreBackend.query(COLLECTION)
        if rows is None:
            return list(cls._pending.values())
        out = []
        for row in rows:
            try:
                out.append(ApprovalRecord(**row))
            except Exception:
                continue
        return out

    @classmethod
    def clear(cls) -> None:
        """Test helper."""
        cls._pending.clear()
