"""In-transit AI firewall.

The central design decision here is that **inbound evidence and outbound
actions get different rule sets**, because they are different kinds of thing:

- *Inbound* telemetry is untrusted **data**. Alerts, stack traces, and slow-query
  logs routinely quote SQL and shell commands — that is what an incident looks
  like. Screening evidence for the word ``DROP TABLE`` and refusing the alert
  means the security layer breaks the product's primary use case. Inbound is
  screened for instruction-hijacking and PII only.

- *Outbound* tool invocations are **actions**. That is the correct place to
  refuse a destructive verb, because that is the only place one could do harm.

Merging the two is the bug this module was written to fix: a legitimate P1 whose
log excerpt mentioned ``DROP TABLE staging_tmp`` was rejected with HTTP 400.

All timings here are measured. There are no latency floors.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Tuple

from app.models import SecurityVerdict, ModelArmorScanResult

# Attempts to hijack the agent's instructions. These are genuinely adversarial
# in inbound data and are blocked.
INJECTION_PATTERNS: List[Tuple[str, str]] = [
    (r"ignore\s+(all\s+)?(previous|prior|above|system)\s+instructions", "instruction_override"),
    (r"disregard\s+(all\s+)?(previous|prior|your)\s+(instructions|rules|training)", "instruction_override"),
    (r"system\s*override", "instruction_override"),
    (r"you\s+are\s+now\s+in\s+(developer|god|dan|unrestricted|sudo|admin)\s+mode", "role_hijack"),
    (r"(reveal|print|show|output)\s+your\s+(system\s+prompt|instructions|credentials|api[_\s]?key)", "prompt_extraction"),
    (r"dump\s+(all\s+)?(passwords|tokens|secrets|api[_\s]?keys|environment\s+variables|env\s+vars)", "secret_exfiltration"),
    (r"forget\s+(everything|all\s+previous)", "instruction_override"),
    (r"new\s+instructions?\s*:", "instruction_injection"),
]

# Destructive verbs. These are NOT blocked inbound — an alert may legitimately
# quote them — but they are refused at the tool-invocation boundary.
DESTRUCTIVE_PATTERNS: List[Tuple[str, str]] = [
    (r"\brm\s+-rf\b", "shell_destructive"),
    (r"\bDROP\s+(DATABASE|TABLE|SCHEMA)\b", "sql_destructive"),
    (r"\bTRUNCATE\s+TABLE\b", "sql_destructive"),
    (r"\bDELETE\s+FROM\b(?!.*\bWHERE\b)", "sql_unbounded_delete"),
    (r"gcloud\s+(projects|sql\s+instances)\s+delete", "gcp_destructive"),
    (r"gsutil\s+rm\s+-r", "gcs_destructive"),
    (r"kubectl\s+delete\s+(ns|namespace|node|pvc)", "k8s_destructive"),
    (r"\bformat\s+[a-zA-Z]:", "disk_destructive"),
]

# PII / secret material redacted from anything before it reaches a model.
# Note: email addresses are deliberately absent — on-call rotations and alert
# routing put real addresses in legitimate telemetry, and masking them destroys
# information the SRE agent needs.
PII_RULES: Dict[str, Tuple[str, str]] = {
    "ssn": (r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]"),
    "credit_card": (r"\b(?:\d{4}[-\s]?){3}\d{4}\b", "[REDACTED_CARD]"),
    "google_api_key": (r"AIza[0-9A-Za-z\-_]{35}", "[REDACTED_GOOGLE_API_KEY]"),
    "gcp_oauth_key": (r"\bAQ\.[A-Za-z0-9\-_]{20,}", "[REDACTED_GCP_KEY]"),
    "github_token": (r"gh[pousr]_[0-9a-zA-Z]{36,}", "[REDACTED_GITHUB_TOKEN]"),
    "aws_access_key": (r"\bAKIA[0-9A-Z]{16}\b", "[REDACTED_AWS_KEY]"),
    "jwt": (r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+", "[REDACTED_JWT]"),
    "private_key": (r"-----BEGIN\s+(RSA\s+|EC\s+)?PRIVATE KEY-----", "[REDACTED_PRIVATE_KEY]"),
}


class ToolInvocationRefused(Exception):
    """Raised when an outbound tool call carries a destructive verb."""


class ModelArmorShield:
    """Regex screening layer.

    On Day 4 this gains a real ``modelarmor.googleapis.com`` call in front of
    these rules; the regex layer stays as defence-in-depth and as the offline
    path, so behaviour is identical with or without network access.
    """

    # ------------------------------------------------------ inbound evidence

    @classmethod
    def screen_inbound(cls, raw: str, user_role: str = "engineer") -> ModelArmorScanResult:
        """Screen untrusted inbound data before it reaches a model.

        Blocks instruction-hijacking. Redacts secrets. Does **not** block
        destructive verbs — quoted commands in an alert are evidence.
        """
        started = time.perf_counter()

        if not raw or not raw.strip():
            return ModelArmorScanResult(
                is_safe=True,
                verdict=SecurityVerdict.ALLOWED,
                sanitized_prompt="",
                latency_ms=round((time.perf_counter() - started) * 1000, 4),
            )

        threats = [
            f"{label}: matched /{pattern}/"
            for pattern, label in INJECTION_PATTERNS
            if re.search(pattern, raw, re.IGNORECASE)
        ]

        if threats:
            return ModelArmorScanResult(
                is_safe=False,
                verdict=SecurityVerdict.QUARANTINED,
                sanitized_prompt="",
                detected_threats=threats,
                latency_ms=round((time.perf_counter() - started) * 1000, 4),
            )

        sanitized, redactions = cls._redact(raw)
        return ModelArmorScanResult(
            is_safe=True,
            verdict=SecurityVerdict.ALLOWED,
            sanitized_prompt=sanitized,
            redacted_pii=redactions,
            latency_ms=round((time.perf_counter() - started) * 1000, 4),
        )

    @classmethod
    def neutralize_inbound(cls, raw: str) -> ModelArmorScanResult:
        """Screen inbound evidence without discarding it.

        Used on incident telemetry. An injection attempt inside a log line is a
        fact about the incident worth keeping, so instead of refusing the whole
        alert the offending span is defanged and the alert proceeds with the
        threat recorded. The agent's action space is closed by enum anyway, so
        neutralised text cannot reach a destructive verb.
        """
        started = time.perf_counter()
        threats: List[str] = []
        text = raw or ""

        for pattern, label in INJECTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                threats.append(f"{label}: matched /{pattern}/")
                text = re.sub(pattern, "[NEUTRALIZED_INJECTION]", text, flags=re.IGNORECASE)

        text, redactions = cls._redact(text)
        return ModelArmorScanResult(
            is_safe=True,
            verdict=SecurityVerdict.QUARANTINED if threats else SecurityVerdict.ALLOWED,
            sanitized_prompt=text,
            detected_threats=threats,
            redacted_pii=redactions,
            latency_ms=round((time.perf_counter() - started) * 1000, 4),
        )

    # -------------------------------------------------------- outbound tools

    @classmethod
    def screen_tool_invocation(cls, tool_name: str, parameters: Dict[str, Any]) -> None:
        """Refuse a destructive outbound action. Raises rather than returning.

        This is the correct boundary for destructive-verb screening: the only
        point at which such a verb could actually do harm.
        """
        haystack = f"{tool_name} {parameters}"
        for pattern, label in DESTRUCTIVE_PATTERNS:
            if re.search(pattern, haystack, re.IGNORECASE):
                raise ToolInvocationRefused(
                    f"Tool invocation refused: {label} matched /{pattern}/ "
                    f"in {tool_name!r}."
                )

    # ------------------------------------------------------------- internals

    @staticmethod
    def _redact(text: str) -> Tuple[str, List[str]]:
        redactions: List[str] = []
        for name, (pattern, replacement) in PII_RULES.items():
            matches = re.findall(pattern, text)
            if matches:
                redactions.append(f"{name} ({len(matches)} masked)")
                text = re.sub(pattern, replacement, text)
        return text, redactions

    # ---------------------------------------------------- backwards-compatible

    @classmethod
    def sanitize_prompt(cls, raw_prompt: str, user_role: str = "engineer") -> ModelArmorScanResult:
        """Retained for the adversarial-studio endpoint, which screens a prompt
        a human typed rather than telemetry a system emitted."""
        return cls.screen_inbound(raw_prompt, user_role=user_role)
