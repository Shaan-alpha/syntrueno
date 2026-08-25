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

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.models import SecurityVerdict, ModelArmorScanResult

logger = logging.getLogger(__name__)

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
    """Two screening layers whose union is stronger than either alone.

    The regex rules above catch the injection phrasings they were written for
    and nothing else. ``modelarmor.googleapis.com`` catches paraphrases no
    regex can enumerate. Measured on 2026-08-25 against this project's
    template, over 8 paraphrased injections that match none of the patterns
    above and 10 benign SRE alerts:

    ==========================  =============  ==============  =============
    Layer                       novel caught   false positive  known attacks
    ==========================  =============  ==============  =============
    regex only                  0/8            0/10            5/5
    Model Armor LOW_AND_ABOVE   4/8            1/10            5/5
    Model Armor HIGH            0/8            0/10            4/5
    **union (regex + LOW)**     **4/8**        **1/10**        **5/5**
    ==========================  =============  ==============  =============

    So the template runs at ``LOW_AND_ABOVE``: the recall is the entire reason
    to make a network call, and the one false positive is affordable *here
    specifically* because the path telemetry takes is
    :meth:`neutralize_inbound`, which defangs and proceeds rather than
    refusing. A false positive costs a flag on a real incident, not a dropped
    one. Raising the confidence to remove that flag also removes the recall
    that justified the call.

    The remote layer is additive and never authoritative on its own: when it
    is unreachable the regex verdict still stands and the result says
    ``degraded_reason``, so a clean scan is distinguishable from an unscreened
    one. Behaviour with no network is the offline behaviour, not a failure.
    """

    _client: Any = None
    _init_failed: bool = False

    # -------------------------------------------------------- remote screening

    @classmethod
    def _get_client(cls) -> Any:
        """Lazy client. Importing this module must never need credentials."""
        if cls._client is not None or cls._init_failed:
            return cls._client
        try:
            from google.api_core.client_options import ClientOptions
            from google.cloud import modelarmor_v1

            cls._client = modelarmor_v1.ModelArmorClient(
                client_options=ClientOptions(
                    api_endpoint=(
                        f"modelarmor.{settings.MODEL_ARMOR_LOCATION}"
                        f".rep.googleapis.com"
                    )
                )
            )
        except Exception as exc:  # pragma: no cover - import/credential failure
            logger.warning("Model Armor client init failed: %s", exc)
            cls._init_failed = True
            cls._client = None
        return cls._client

    @classmethod
    def reset(cls) -> None:
        """Drop the cached client. Used by tests that flip settings."""
        cls._client = None
        cls._init_failed = False

    @classmethod
    def _remote_scan(cls, text: str) -> Tuple[List[str], Optional[str]]:
        """Screen ``text`` with Model Armor.

        Returns ``(threat_labels, degraded_reason)``. Never raises: a security
        layer that can crash the request it screens is a liability, and the
        regex layer is a complete verdict on its own.
        """
        if not settings.USE_REAL_MODEL_ARMOR or not text.strip():
            return [], None

        client = cls._get_client()
        if client is None:
            return [], "model_armor_client_unavailable"

        try:
            from google.cloud import modelarmor_v1

            name = (
                f"projects/{settings.GOOGLE_CLOUD_PROJECT}"
                f"/locations/{settings.MODEL_ARMOR_LOCATION}"
                f"/templates/{settings.MODEL_ARMOR_TEMPLATE_ID}"
            )
            response = client.sanitize_user_prompt(
                request=modelarmor_v1.SanitizeUserPromptRequest(
                    name=name,
                    user_prompt_data=modelarmor_v1.DataItem(text=text),
                )
            )
            result = response.sanitization_result
            if result.filter_match_state.name != "MATCH_FOUND":
                return [], None

            # Name the filters that actually matched, not every filter in the
            # template -- "sdp" on a scan that only tripped jailbreak detection
            # would send an operator looking for a leaked secret that is not
            # there.
            labels = [
                f"model_armor: {filter_name} matched"
                for filter_name, filter_result in result.filter_results.items()
                if cls._filter_matched(filter_result)
            ]
            return labels or ["model_armor: policy matched"], None

        except Exception as exc:
            logger.warning("Model Armor scan failed: %s", str(exc)[:200])
            return [], f"model_armor_unreachable:{type(exc).__name__}"

    @staticmethod
    def _filter_matched(filter_result: Any) -> bool:
        """True when this specific filter reported a match.

        ``filter_results`` returns a populated wrapper per configured filter
        whether or not it fired, so the match state has to be read off the one
        populated sub-result. Substring-testing the repr for "MATCH_FOUND"
        does not work -- "NO_MATCH_FOUND" contains it.
        """
        for attr in (
            "pi_and_jailbreak_filter_result",
            "sdp_filter_result",
            "malicious_uri_filter_result",
            "rai_filter_result",
            "csam_filter_result",
        ):
            sub = getattr(filter_result, attr, None)
            state = getattr(sub, "match_state", None)
            if state is not None and state.name == "MATCH_FOUND":
                return True
        return False

    @classmethod
    def _gemma_scan(cls, text: str) -> Tuple[List[str], Optional[str]]:
        """Screen ``text`` with Gemma. Returns ``(threat_labels, degraded)``.

        Gemma catches paraphrases neither the regex layer nor Model Armor can
        match -- measured 8/8 on a corpus where those two score 0/8 and 4/8.
        It also failed 2 of 10 calls in the same run, so it is advisory: a
        failure is reported, never raised, and never blocks the alert.
        """
        if not settings.USE_GEMMA_SCREEN:
            return [], None

        from app.llm.gemma import GemmaScreen

        verdict = GemmaScreen.screen(text)
        if not verdict.ok:
            return [], verdict.degraded_reason
        if not verdict.is_injection:
            return [], None

        reason = (verdict.reason or "policy matched").strip()
        return [f"gemma: {reason[:120]}"], None

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

        remote_threats, degraded = cls._remote_scan(raw)
        threats += remote_threats
        screened_by = ["regex"] + ([] if degraded else cls._remote_layer())

        if threats:
            return ModelArmorScanResult(
                is_safe=False,
                verdict=SecurityVerdict.QUARANTINED,
                sanitized_prompt="",
                detected_threats=threats,
                latency_ms=round((time.perf_counter() - started) * 1000, 4),
                screened_by=screened_by,
                degraded_reason=degraded,
            )

        sanitized, redactions = cls._redact(raw)
        return ModelArmorScanResult(
            is_safe=True,
            verdict=SecurityVerdict.ALLOWED,
            sanitized_prompt=sanitized,
            redacted_pii=redactions,
            latency_ms=round((time.perf_counter() - started) * 1000, 4),
            screened_by=screened_by,
            degraded_reason=degraded,
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

        # Both remote layers screen what actually arrived, before the regex
        # layer rewrites any of it -- scanning already-neutralised text would
        # hide the very span they are meant to judge.
        #
        # Run concurrently: sequentially this costs armor + gemma, and Gemma's
        # benign-corpus median alone was 6.3s.
        with ThreadPoolExecutor(max_workers=2) as pool:
            armor_future = pool.submit(cls._remote_scan, text)
            gemma_future = pool.submit(cls._gemma_scan, text)
            remote_threats, armor_degraded = armor_future.result()
            gemma_threats, gemma_degraded = gemma_future.result()

        remote_threats = list(remote_threats) + list(gemma_threats)
        degraded = "; ".join(r for r in (armor_degraded, gemma_degraded) if r) or None

        for pattern, label in INJECTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                threats.append(f"{label}: matched /{pattern}/")
                text = re.sub(pattern, "[NEUTRALIZED_INJECTION]", text, flags=re.IGNORECASE)

        # A remote match carries a verdict but no span, so there is nothing to
        # excise. The alert proceeds flagged rather than refused: the agent's
        # action space is a closed enum, so text the regex layer did not
        # recognise still cannot reach a destructive verb.
        threats += remote_threats

        text, redactions = cls._redact(text)
        return ModelArmorScanResult(
            is_safe=True,
            verdict=SecurityVerdict.QUARANTINED if threats else SecurityVerdict.ALLOWED,
            sanitized_prompt=text,
            detected_threats=threats,
            redacted_pii=redactions,
            latency_ms=round((time.perf_counter() - started) * 1000, 4),
            screened_by=cls._layers_that_ran(armor_degraded, gemma_degraded),
            degraded_reason=degraded,
        )

    @classmethod
    def _layers_that_ran(
        cls, armor_degraded: Optional[str], gemma_degraded: Optional[str]
    ) -> List[str]:
        """Only layers that actually returned a verdict are named.

        A layer that timed out has not screened anything, and listing it would
        make an incomplete scan read as a thorough one.
        """
        layers = ["regex"]
        if settings.USE_REAL_MODEL_ARMOR and not armor_degraded:
            layers.append("model_armor")
        if settings.USE_GEMMA_SCREEN and not gemma_degraded:
            layers.append("gemma")
        return layers

    @staticmethod
    def _remote_layer() -> List[str]:
        """["model_armor"] when the remote layer is configured, else []."""
        return ["model_armor"] if settings.USE_REAL_MODEL_ARMOR else []

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
