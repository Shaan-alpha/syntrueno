from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "Syntrueno"
    ENGINE_NAME: str = "ThorForja"
    VERSION: str = "2.0.0"
    ENVIRONMENT: str = "development"

    # --- Google Cloud ---
    GOOGLE_CLOUD_PROJECT: str = "composed-maxim-498517-f0"
    GOOGLE_CLOUD_PROJECT_NUMBER: str = "18489510475"
    GOOGLE_CLOUD_LOCATION: str = "us-central1"

    # --- Gemini ---
    # Verified 2026-08-22: gemini-2.5-* returns 404 for new API keys, and
    # pro-latest / 3.1-pro-preview return 429 on the free tier. Measured
    # latency: flash-lite ~8.5s (thinking off), 3.6-flash ~25.4s (thinking on).
    GEMINI_API_KEY: Optional[str] = None
    USE_VERTEX_AI: bool = False
    FAST_MODEL: str = "gemini-3.1-flash-lite"
    REASONING_MODEL: str = "gemini-3.6-flash"
    FAST_THINKING_BUDGET: int = 0
    LLM_TIMEOUT_SECONDS: int = 45
    LLM_MAX_RETRIES: int = 3

    # --- Firestore ---
    FIRESTORE_ENABLED: bool = False
    FIRESTORE_DATABASE: str = "(default)"

    # --- Model Armor ---
    MODEL_ARMOR_ENABLED: bool = True
    USE_REAL_MODEL_ARMOR: bool = False
    MODEL_ARMOR_TEMPLATE_ID: str = "syntrueno-enterprise-standard"
    MODEL_ARMOR_LOCATION: str = "us-central1"

    # --- Zero-trust A2A ---
    A2A_AUTH_SECRET: str = "dev-only-insecure-secret-override-in-env"
    A2A_TOKEN_TTL_SECONDS: int = 120

    # --- Remediation guardrails ---
    # Only this service may ever be mutated. Enforced in app/cloud/runadmin.py.
    CANARY_SERVICE_NAME: str = "syntrueno-canary"
    REMEDIATION_DRY_RUN: bool = True

    # --- Judge thresholds (see spec section 5.1) ---
    JUDGE_AUTO_EXECUTE_THRESHOLD: float = 8.5
    JUDGE_HARD_REFUSAL_THRESHOLD: float = 5.0

    # --- Web ---
    CORS_ALLOWED_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Cost & scale ---
    SIMULATION_MODE: bool = True
    MAX_CONCURRENT_TASKS: int = 5

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def llm_available(self) -> bool:
        """True when a real Gemini call could succeed."""
        return bool(self.GEMINI_API_KEY) and not self.SIMULATION_MODE


settings = Settings()
