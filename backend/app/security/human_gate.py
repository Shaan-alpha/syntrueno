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
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.models import ApprovalRecord, RemediationAction


class ApprovalNotFound(Exception):
    """No pending approval with that id."""


class ApprovalStateError(Exception):
    """The approval exists but is not in a signable state."""


class HumanApprovalGate:
    """Server-side approval store.

    Backed by a process-local dict today; Day 2 swaps the backend for Firestore
    without changing this interface.
    """

    _pending: Dict[str, ApprovalRecord] = {}

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
        )
        cls._pending[record.approval_id] = record
        return record

    @classmethod
    def get(cls, approval_id: str) -> Optional[ApprovalRecord]:
        return cls._pending.get(approval_id)

    @classmethod
    def sign_approval(cls, approval_id: str, engineer_id: str) -> ApprovalRecord:
        """Sign a pending approval by id.

        The caller supplies only which approval to sign and who is signing. The
        action itself comes from the server's stored copy, so there is nothing
        for a caller to forge.
        """
        record = cls._pending.get(approval_id)
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
        return record

    @classmethod
    def reject_approval(cls, approval_id: str, engineer_id: str) -> ApprovalRecord:
        record = cls._pending.get(approval_id)
        if record is None:
            raise ApprovalNotFound(f"No pending approval {approval_id!r}.")
        record.status = "REJECTED"
        record.signed_by = engineer_id
        record.signed_at = datetime.now(timezone.utc).isoformat()
        return record

    # ----------------------------------------------------- execution check

    @classmethod
    def authorises(cls, action: RemediationAction) -> bool:
        """True when a signed approval exists for exactly this action.

        Called by the remediation layer immediately before mutating anything.
        A signature for one action never authorises another, because the hash
        covers the tool, its parameters, and its tier.
        """
        target = cls.compute_action_hash(action)
        return any(
            r.status == "APPROVED" and r.action_hash == target
            for r in cls._pending.values()
        )

    # ---------------------------------------------------------- inspection

    @classmethod
    def list_all(cls) -> List[ApprovalRecord]:
        return list(cls._pending.values())

    @classmethod
    def clear(cls) -> None:
        """Test helper."""
        cls._pending.clear()
