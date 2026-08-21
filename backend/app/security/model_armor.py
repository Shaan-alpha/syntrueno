import re
import time
from typing import Tuple, List, Dict, Any
from app.models import SecurityVerdict, ModelArmorScanResult

class ModelArmorShield:
    """
    Enterprise-Grade In-Transit AI Firewall simulating Google Cloud Model Armor.
    Screens prompts and tool outputs for adversarial injections, destructive commands,
    and sensitive enterprise PII (DLP).
    """
    
    JAILBREAK_PATTERNS = [
        r"ignore\s+(all\s+)?(previous|prior|system)\s+instructions",
        r"system\s*override",
        r"you\s+are\s+now\s+in\s+(developer|god|dan|unrestricted|sudo)\s+mode",
        r"reveal\s+your\s+(system\s+prompt|credentials|api_key|secret|hidden\s+instructions)",
        r"dump\s+(all\s+)?(passwords|tokens|keys|environment\s+variables|env\s+vars)",
        r"rm\s+-rf",
        r"DROP\s+(DATABASE|TABLE|SCHEMA)",
        r"TRUNCATE\s+TABLE",
        r"gcloud\s+projects\s+delete",
        r"gsutil\s+rm\s+-r",
        r"kubectl\s+delete\s+(ns|namespace|node|pod\s+--all)",
        r"format\s+[a-zA-Z]:",
        r"UNION\s+ALL\s+SELECT",
        r"OR\s+1\s*=\s*1",
        r"<script.*?>.*?</script.*?>",
    ]
    
    PII_RULES = {
        "ssn": (r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]"),
        "credit_card": (r"\b(?:\d{4}[-\s]?){3}\d{4}\b", "[REDACTED_CARD]"),
        "google_api_key": (r"AIza[0-9A-Za-z-_]{35}", "[REDACTED_GOOGLE_API_KEY]"),
        "github_token": (r"ghp_[0-9a-zA-Z]{36}", "[REDACTED_GITHUB_TOKEN]"),
        "jwt_token": (r"eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]+", "[REDACTED_JWT]"),
        "email_address": (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[REDACTED_EMAIL]"),
        "ip_address": (r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b", "[REDACTED_INTERNAL_IP]"),
    }

    @classmethod
    def sanitize_prompt(cls, raw_prompt: str, user_role: str = "engineer") -> ModelArmorScanResult:
        """Inspects prompt in-transit before LLM processing."""
        start_time = time.perf_counter()
        threats_detected: List[str] = []
        pii_redacted: List[str] = []

        if not raw_prompt or not raw_prompt.strip():
            return ModelArmorScanResult(
                is_safe=True,
                verdict=SecurityVerdict.ALLOWED,
                sanitized_prompt="",
                detected_threats=[],
                redacted_pii=[],
                latency_ms=0.1,
            )

        # 1. Prompt Injection & Destructive Command Interception
        for pattern in cls.JAILBREAK_PATTERNS:
            if re.search(pattern, raw_prompt, re.IGNORECASE):
                threats_detected.append(f"Adversarial security policy violation: matched rule '{pattern}'")

        if threats_detected:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return ModelArmorScanResult(
                is_safe=False,
                verdict=SecurityVerdict.BLOCKED,
                sanitized_prompt="",
                detected_threats=threats_detected,
                redacted_pii=[],
                latency_ms=max(duration_ms, 12.4),
            )

        # 2. PII Data Loss Prevention (DLP) Sanitization & Masking
        sanitized = raw_prompt
        for pii_name, (pattern, replacement) in cls.PII_RULES.items():
            matches = re.findall(pattern, sanitized)
            if matches:
                pii_redacted.append(f"{pii_name} ({len(matches)} item(s) masked)")
                sanitized = re.sub(pattern, replacement, sanitized)

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return ModelArmorScanResult(
            is_safe=True,
            verdict=SecurityVerdict.ALLOWED,
            sanitized_prompt=sanitized,
            detected_threats=[],
            redacted_pii=pii_redacted,
            latency_ms=max(duration_ms, 8.2),
        )
