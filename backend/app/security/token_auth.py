"""Zero-trust capability tokens for agent-to-agent dispatch.

Short-lived, HMAC-SHA256 signed, and scoped to a single (audience, capability)
pair. A token minted for the SRE agent's ``diagnose_incident`` capability
cannot be replayed against the Auditor, and cannot be used to request a
different capability from the same agent.

Naming note: these are **not** JWTs. The encoding is base64url of compact JSON
with an HMAC tag, which is JWT-shaped but not JWT-compliant, and the agent card
declares them as ``a2a-capability-token`` rather than claiming ``bearer_jwt``.
Calling a thing what it actually is matters more here than the label sounding
familiar.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict

from app.config import settings


class CapabilityDenied(Exception):
    """The presented token does not authorise this call."""


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class A2ATokenAuthority:
    """Mints and verifies scoped capability tokens."""

    @staticmethod
    def _sign(header_b64: str, payload_b64: str) -> str:
        return _b64u_encode(
            hmac.new(
                settings.A2A_AUTH_SECRET.encode(),
                f"{header_b64}.{payload_b64}".encode(),
                hashlib.sha256,
            ).digest()
        )

    @classmethod
    def mint_token(
        cls,
        source_agent: str,
        target_agent: str,
        capability: str,
        ttl_seconds: int | None = None,
    ) -> str:
        ttl = ttl_seconds if ttl_seconds is not None else settings.A2A_TOKEN_TTL_SECONDS
        header = {"alg": "HS256", "typ": "A2A-CAP"}
        payload = {
            "iss": source_agent,
            "aud": target_agent,
            "cap": capability,
            "iat": int(time.time()),
            "exp": int(time.time()) + ttl,
        }
        h = _b64u_encode(json.dumps(header, separators=(",", ":")).encode())
        p = _b64u_encode(json.dumps(payload, separators=(",", ":")).encode())
        return f"{h}.{p}.{cls._sign(h, p)}"

    @classmethod
    def decode(cls, token: str) -> Dict[str, Any]:
        """Verify the signature and return the payload. Raises on any problem."""
        parts = token.split(".")
        if len(parts) != 3:
            raise CapabilityDenied("Malformed capability token.")

        h, p, signature = parts
        if not hmac.compare_digest(signature, cls._sign(h, p)):
            raise CapabilityDenied("Capability token signature is invalid.")

        try:
            payload = json.loads(_b64u_decode(p).decode())
        except Exception as exc:
            raise CapabilityDenied(f"Unreadable capability token payload: {exc}")

        if payload.get("exp", 0) < time.time():
            raise CapabilityDenied("Capability token has expired.")
        return payload

    @classmethod
    def require(cls, token: str, expected_target: str, required_capability: str) -> Dict[str, Any]:
        """Assert that ``token`` authorises ``required_capability`` on
        ``expected_target``. Raises ``CapabilityDenied`` otherwise."""
        payload = cls.decode(token)

        if payload.get("aud") != expected_target:
            raise CapabilityDenied(
                f"Token audience {payload.get('aud')!r} does not match "
                f"{expected_target!r}."
            )

        granted = payload.get("cap")
        if granted != required_capability and granted != "*":
            raise CapabilityDenied(
                f"Token grants {granted!r}, which does not cover "
                f"{required_capability!r}."
            )
        return payload

    @classmethod
    def verify_token(
        cls, token: str, expected_target: str, required_capability: str
    ) -> bool:
        """Boolean form of :meth:`require`."""
        try:
            cls.require(token, expected_target, required_capability)
            return True
        except CapabilityDenied:
            return False
