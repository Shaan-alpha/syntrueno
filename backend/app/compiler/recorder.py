from typing import List, Dict, Any
from datetime import datetime, timezone

class TrajectoryRecorder:
    """Logs successful multi-turn tool trajectories for recurring pattern mining."""
    
    _trajectories: List[Dict[str, Any]] = []

    @classmethod
    def record_trajectory(cls, incident_type: str, tool_sequence: List[str], parameters: Dict[str, Any], duration_ms: float):
        cls._trajectories.append({
            "incident_type": incident_type,
            "tool_sequence": tool_sequence,
            "parameters": parameters,
            "duration_ms": duration_ms,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })

    @classmethod
    def get_all_trajectories(cls) -> List[Dict[str, Any]]:
        return list(cls._trajectories)

    @classmethod
    def clear(cls):
        cls._trajectories.clear()
