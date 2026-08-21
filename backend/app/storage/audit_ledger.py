import hashlib
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from app.models import AuditLogEntry

class AuditLedger:
    """Tamper-evident append-only audit ledger with SHA-256 hash chaining."""
    
    _ledger_entries: List[Dict[str, Any]] = []
    _latest_hash: str = "0000000000000000000000000000000000000000000000000000000000000000"

    @classmethod
    def record_entry(cls, entry: AuditLogEntry) -> str:
        entry_dict = entry.model_dump()
        payload_str = json.dumps(entry_dict, sort_keys=True)
        
        # Compute chained hash: H(AuditState(t) || Event(t+1))
        chain_input = f"{cls._latest_hash}:{payload_str}"
        entry_hash = hashlib.sha256(chain_input.encode()).hexdigest()
        
        entry_dict["chain_hash"] = entry_hash
        entry_dict["prev_hash"] = cls._latest_hash
        
        cls._ledger_entries.append(entry_dict)
        cls._latest_hash = entry_hash
        return entry_hash

    @classmethod
    def get_all_entries(cls) -> List[Dict[str, Any]]:
        return list(cls._ledger_entries)

    @classmethod
    def verify_integrity(cls) -> bool:
        current_hash = "0000000000000000000000000000000000000000000000000000000000000000"
        for item in cls._ledger_entries:
            saved_chain_hash = item["chain_hash"]
            clean_item = {k: v for k, v in item.items() if k not in ("chain_hash", "prev_hash")}
            payload_str = json.dumps(clean_item, sort_keys=True)
            expected_hash = hashlib.sha256(f"{current_hash}:{payload_str}".encode()).hexdigest()
            if saved_chain_hash != expected_hash:
                return False
            current_hash = saved_chain_hash
        return True
