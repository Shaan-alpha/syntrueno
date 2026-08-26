from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "Syntrueno"
    VERSION: str = "2.0.0"
    ENVIRONMENT: str = "development"

    # --- Google Cloud ---
    GOOGLE_CLOUD_PROJECT: str = "composed-maxim-498517-f0"
    GOOGLE_CLOUD_LOCATION: str = "us-central1"

    # Vertex serves Gemini from its own location, which is NOT the region the
    # rest of the stack runs in. Verified by execution on 2026-08-25 against
    # this project: in ``us-central1`` every ``gemini-3.x`` model returns 404
    # NOT_FOUND, while ``global`` serves all of them. Reusing
    # GOOGLE_CLOUD_LOCATION here would silently break the whole model chain.
    VERTEX_LOCATION: str = "global"

    # --- Gemini ---
    # Verified 2026-08-22: gemini-2.5-* returns 404 for new API keys, and
    # pro-latest / 3.1-pro-preview return 429 on the free tier. Measured
    # latency: flash-lite ~8.5s (thinking off), 3.6-flash ~25.4s (thinking on).
    # Every model here is 3.5 or newer. The hackathon's eligibility gate is a
    # pass/fail check on "Gemini 3.5+", and gemini-3.1-flash-lite sat below it.
    # Measured on Vertex 2026-08-25: 3.7-flash returns structured output in
    # ~2.1s against flash-lite's ~1.4s, which is a cheap price for removing a
    # disqualification question from the submission entirely.
    GEMINI_API_KEY: Optional[str] = None
    USE_VERTEX_AI: bool = False
    FAST_MODEL: str = "gemini-3.5-flash"
    REASONING_MODEL: str = "gemini-3.6-flash"
    FAST_THINKING_BUDGET: int = 0
    LLM_TIMEOUT_SECONDS: int = 45
    LLM_MAX_RETRIES: int = 3

    # Free-tier daily caps are per-model, and the thinking-capable Flash models
    # allow only 20 requests/day each. Falling back across models instead of
    # retrying one pools the budget:
    #   3.6-flash 20 + 3.7-flash 20 + 3.5-flash 20 + flash-lite 500 = 560/day
    # Order is best-quality-first; the chain degrades rather than failing.
    REASONING_MODEL_CHAIN: str = "gemini-3.6-flash,gemini-3.7-flash,gemini-3.5-flash"
    FAST_MODEL_CHAIN: str = "gemini-3.5-flash,gemini-3.7-flash"

    # --- Gemma screening (third inbound layer) ---
    # Gemma is served by the AI Studio API, not Vertex: five gemma-* names all
    # returned 404 from Vertex at the "global" location on 2026-08-25, while
    # models.list() on the AI Studio key returns gemma-4-26b-a4b-it. So this
    # path uses GEMINI_API_KEY even when USE_VERTEX_AI is true.
    #
    # Measured over 18 samples: it caught 8/8 paraphrased injections that regex
    # and Model Armor both miss, with 0 false positives -- and failed outright
    # on 2 of 10 calls. A layer that fails one call in five is advisory, never
    # a gate.
    USE_GEMMA_SCREEN: bool = False
    GEMMA_MODEL: str = "gemma-4-26b-a4b-it"
    # Benign-corpus median was 6.3s. An incident completes in ~8s, so an
    # unbounded call would take it to ~14s. This bounds the worst case at +3s
    # and drops the layer's contribution on slow calls, which is the trade.
    GEMMA_TIMEOUT_SECONDS: float = 3.0

    # --- Vertex AI Memory Bank (Agent Engine) ---
    # Agent Engine is the exact inverse of Gemini on Vertex. Verified by
    # execution 2026-08-26: gemini-3.x 404s in us-central1 and serves from
    # "global", while reasoningEngines 404 at "global" and serve from
    # us-central1. Reusing VERTEX_LOCATION here would silently break every
    # memory call, which is the third time this codebase has met this bug --
    # see GOOGLE_CLOUD_LOCATION above, and VERTEX_LOCATION itself.
    VERTEX_MEMORY_ENABLED: bool = False
    AGENT_ENGINE_LOCATION: str = "us-central1"
    AGENT_ENGINE_ID: str = ""
    # Recall sits inside the incident path. An incident completes in ~8s and
    # this bounds the layer's worst-case contribution, the same trade as
    # GEMMA_TIMEOUT_SECONDS. Firestore answers when this expires.
    VERTEX_MEMORY_TIMEOUT_SECONDS: float = 4.0

    # --- Agent Observability (OpenTelemetry -> Cloud Trace) ---
    # Off by default so the test suite and local runs never open an exporter.
    # Spans are batched on a background thread: a slow or unreachable Cloud
    # Trace must never appear as incident latency.
    TRACING_ENABLED: bool = False

    # --- Firestore ---
    FIRESTORE_ENABLED: bool = False
    FIRESTORE_DATABASE: str = "(default)"

    # --- Model Armor ---
    MODEL_ARMOR_ENABLED: bool = True
    USE_REAL_MODEL_ARMOR: bool = False
    MODEL_ARMOR_TEMPLATE_ID: str = "syntrueno-enterprise-standard"
    MODEL_ARMOR_LOCATION: str = "us-central1"

    # --- Event-driven ingestion (Cloud Monitoring -> Pub/Sub -> webhook) ---
    # Off by default. This is the one path that reaches the swarm with no human
    # in the loop, so it stays shut until an operator configures who may call
    # it. PUBSUB_PUSH_SERVICE_ACCOUNT has no default on purpose: an empty
    # expectation would accept any Google-issued OIDC token, and the ingest
    # code refuses rather than treating "unset" as "allow".
    PUBSUB_INGEST_ENABLED: bool = False
    PUBSUB_PUSH_SERVICE_ACCOUNT: str = ""
    PUBSUB_AUDIENCE: str = ""

    # --- Zero-trust A2A ---
    A2A_AUTH_SECRET: str = "dev-only-insecure-secret-override-in-env"
    A2A_TOKEN_TTL_SECONDS: int = 120

    # --- Remediation guardrails ---
    # Only this service may ever be mutated. Enforced in app/cloud/runadmin.py.
    CANARY_SERVICE_NAME: str = "syntrueno-canary"
    REMEDIATION_DRY_RUN: bool = True

    # --- Judge thresholds (see spec section 5.1) ---
    APPROVAL_TTL_MINUTES: int = 30
    JUDGE_AUTO_EXECUTE_THRESHOLD: float = 8.5
    JUDGE_HARD_REFUSAL_THRESHOLD: float = 5.0

    # --- Web ---
    CORS_ALLOWED_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Cost & scale ---
    SIMULATION_MODE: bool = True

    def model_chain(self, tier: str) -> List[str]:
        """Ordered model candidates for a tier, best quality first."""
        raw = (
            self.REASONING_MODEL_CHAIN
            if tier == "reasoning"
            else self.FAST_MODEL_CHAIN
        )
        chain = [m.strip() for m in raw.split(",") if m.strip()]
        preferred = (
            self.REASONING_MODEL if tier == "reasoning" else self.FAST_MODEL
        )
        # Whatever the operator pinned goes first, without duplicating it.
        return [preferred] + [m for m in chain if m != preferred]

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def llm_available(self) -> bool:
        """True when a real Gemini call could succeed.

        The two backends authenticate differently: AI Studio needs an API key,
        Vertex needs Application Default Credentials and no key at all. Gating
        both on ``GEMINI_API_KEY`` would report a fully-configured Vertex
        deployment as degraded and never place the call.
        """
        if self.SIMULATION_MODE:
            return False
        if self.USE_VERTEX_AI:
            return bool(self.GOOGLE_CLOUD_PROJECT)
        return bool(self.GEMINI_API_KEY)


settings = Settings()
