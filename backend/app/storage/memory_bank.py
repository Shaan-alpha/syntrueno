import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from app.config import settings

class MemoryBank:
    """Persistent organizational memory bank for cross-session incident context and cloud profiles."""
    
    _in_memory_store: Dict[str, Dict[str, Any]] = {
        "org_profile": {
            "org_name": "Acme Global Infrastructure",
            "cloud_budget_monthly_usd": 5000.0,
            "primary_region": "us-central1",
            "db_pool_standard": 150,
            "max_cloud_run_instances": 10,
        },
        "incidents_history": [
            {
                "incident_id": "inc-8902",
                "service": "cloud-run/order-api",
                "root_cause": "OOM container crash from unindexed query",
                "resolution": "Applied B-Tree index on orders(created_at) and bumped memory limit to 1GiB",
                "resolved_at": "2026-08-18T14:30:00Z"
            }
        ]
    }

    @classmethod
    def get_org_profile(cls) -> Dict[str, Any]:
        return cls._in_memory_store["org_profile"]

    @classmethod
    def update_org_profile(cls, updates: Dict[str, Any]) -> Dict[str, Any]:
        cls._in_memory_store["org_profile"].update(updates)
        return cls._in_memory_store["org_profile"]

    @classmethod
    def record_incident_resolution(cls, incident_id: str, service: str, root_cause: str, resolution: str):
        cls._in_memory_store["incidents_history"].append({
            "incident_id": incident_id,
            "service": service,
            "root_cause": root_cause,
            "resolution": resolution,
            "resolved_at": datetime.now(timezone.utc).isoformat()
        })

    @classmethod
    def query_similar_incidents(cls, service_query: str, limit: int = 3) -> List[Dict[str, Any]]:
        history = cls._in_memory_store["incidents_history"]
        matches = [inc for inc in history if service_query.lower() in inc["service"].lower() or service_query.lower() in inc["root_cause"].lower()]
        return matches[:limit] if matches else history[-limit:]
