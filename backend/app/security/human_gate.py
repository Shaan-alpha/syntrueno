import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from app.models import ApprovalRecord, RemediationAction

class HumanApprovalGate:
    """Manages cryptographic Human-in-the-Loop approvals for destructive or high-tier actions."""
    
    @staticmethod
    def compute_action_hash(action: RemediationAction) -> str:
        payload = {
            "tool_name": action.tool_name,
            "parameters": action.parameters,
            "tier": action.tier.value,
        }
        serialized = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()

    @classmethod
    def create_pending_approval(cls, incident_id: str, action: RemediationAction) -> ApprovalRecord:
        action_hash = cls.compute_action_hash(action)
        approval_id = f"appr-{action_hash[:8]}-{incident_id[-4:]}"
        return ApprovalRecord(
            approval_id=approval_id,
            incident_id=incident_id,
            action_hash=action_hash,
            requested_action=action,
            status="PENDING",
        )

    @classmethod
    def sign_approval(cls, record: ApprovalRecord, engineer_id: str) -> ApprovalRecord:
        # Verify action hash integrity
        expected_hash = cls.compute_action_hash(record.requested_action)
        if record.action_hash != expected_hash:
            raise ValueError("Tamper detected: Action parameters do not match action hash!")
            
        record.status = "APPROVED"
        record.signed_by = engineer_id
        record.signed_at = datetime.now(timezone.utc).isoformat()
        return record
