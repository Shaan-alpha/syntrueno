import re
import time
from typing import Tuple, List, Dict, Any
from app.models import SecurityVerdict, ModelArmorScanResult

class ModelArmorShield:
    """Enterprise AI Firewall simulating Google Cloud Model Armor."""
    
    JAILBREAK_PATTERNS = [
        r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
        r"system\s*override",
        r"you\s+are\s+now\s+in\s+(developer|god|dan)\s+mode",
        r"reveal\s+your\s+(system\s+prompt|credentials|api_key|secret)",
        r"dump\s+(all\s+)?(passwords|tokens|keys|environment\s+variables)",
        r"rm\s+-rf",
        r"DROP\s+DATABASE",
        r"DROP\s+TABLE",
        r"format\s+c:",
    ]
    
    PII_RULES = {
        "ssn": (r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]"),
        "credit_card": (r"\b(?:\d{4}[-\s]?){3}\d{4}\b", "[REDACTED_CARD]"),
        "api_key": (r"(AIza[0-9A-Za-z-_]{35}|ghp_[0-9a-zA-Z]{36})", "[REDACTED_API_KEY]"),
        "jwt_token": (r"eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]+", "[REDACTED_JWT]"),
    }

    @classmethod
    def sanitize_prompt(cls, raw_prompt: str, user_role: str = "engineer") -> ModelArmorScanResult:
        """Inspects prompt in-transit before LLM processing."""
        start_time = time.perf_counter()
        threats_detected: List[str] = []
        pii_redacted: List[str] = []

        # 1. Prompt Injection / Jailbreak Check
        for pattern in cls.JAILBREAK_PATTERNS:
            if re.search(pattern, raw_prompt, re.IGNORECASE):
                threats_detected.append(f"Adversarial pattern match: '{pattern}'")

        if threats_detected:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return ModelArmorScanResult(
                is_safe=False,
                verdict=SecurityVerdict.BLOCKED,
                sanitized_prompt="",
                detected_threats=threats_detected,
                redacted_pii=[],
                latency_ms=duration_ms,
            )

        # 2. PII Sanitization & Redaction
        sanitized = raw_prompt
        for pii_name, (pattern, replacement) in cls.PII_RULES.items():
            matches = re.findall(pattern, sanitized)
            if matches:
                pii_redacted.append(f"{pii_name} ({len(matches)} instance(s))")
                sanitized = re.sub(pattern, replacement, sanitized)

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return ModelArmorScanResult(
            is_safe=True,
            verdict=SecurityVerdict.ALLOWED,
            sanitized_prompt=sanitized,
            detected_threats=[],
            redacted_pii=pii_redacted,
            latency_ms=duration_ms,
        )
