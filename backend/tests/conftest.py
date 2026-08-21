import pytest
from unittest.mock import MagicMock, patch

@pytest.fixture(autouse=True)
def mock_google_auth():
    """Patches google.auth.default so tests run 100% offline without GCP credentials."""
    with patch("google.auth.default") as mock_default:
        mock_credentials = MagicMock()
        mock_credentials.valid = True
        mock_default.return_value = (mock_credentials, "mock-sentinel-project")
        yield mock_default

@pytest.fixture
def sample_incident_payload():
    return {
        "incident_id": "inc-9021",
        "service_id": "cloud-run/auth-service",
        "severity": "CRITICAL",
        "metric_name": "db_connection_pool_saturation",
        "error_message": "504 Gateway Timeout: DB connection pool exhausted (>98%)",
        "telemetry_data": {
            "active_connections": 98,
            "max_connections": 100,
            "p99_latency_ms": 4200
        }
    }
