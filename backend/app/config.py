from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    
    PROJECT_NAME: str = "Syntrueno"
    ENGINE_NAME: str = "ThorForja"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    
    # Google Cloud & Gemini Config
    GOOGLE_CLOUD_PROJECT: str = "syntrueno-cloud-fleet"
    GOOGLE_CLOUD_LOCATION: str = "us-central1"
    GEMINI_API_KEY: Optional[str] = None
    
    # Models
    FAST_MODEL: str = "gemini-2.5-flash"
    REASONING_MODEL: str = "gemini-2.5-pro"
    
    # Security & Governance
    MODEL_ARMOR_ENABLED: bool = True
    MODEL_ARMOR_TEMPLATE_ID: str = "template-enterprise-standard"
    A2A_AUTH_SECRET: str = "syntrueno-zero-trust-secret-key-2026"
    
    # Cost & Scalability Controls
    SIMULATION_MODE: bool = True  # Allows offline / mock zero-cost execution
    MAX_CONCURRENT_TASKS: int = 5

settings = Settings()
