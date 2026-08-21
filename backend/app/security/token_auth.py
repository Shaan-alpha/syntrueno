import time
import hmac
import hashlib
import json
from app.config import settings

class A2ATokenAuthority:
    """Issues and verifies cryptographic capability tokens between agents."""
    
    @staticmethod
    def mint_token(source_agent: str, target_agent: str, capability: str, ttl_seconds: int = 120) -> str:
        header = {"alg": "HS256", "typ": "A2A-CAP"}
        payload = {
            "iss": source_agent,
            "aud": target_agent,
            "cap": capability,
            "exp": int(time.time()) + ttl_seconds,
        }
        h_bytes = json.dumps(header).encode().hex()
        p_bytes = json.dumps(payload).encode().hex()
        signature = hmac.new(
            settings.A2A_AUTH_SECRET.encode(),
            f"{h_bytes}.{p_bytes}".encode(),
            hashlib.sha256
        ).hexdigest()
        return f"{h_bytes}.{p_bytes}.{signature}"

    @staticmethod
    def verify_token(token: str, expected_target: str, required_capability: str) -> bool:
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return False
            h_bytes, p_bytes, signature = parts
            expected_sig = hmac.new(
                settings.A2A_AUTH_SECRET.encode(),
                f"{h_bytes}.{p_bytes}".encode(),
                hashlib.sha256
            ).hexdigest()
            
            if not hmac.compare_digest(signature, expected_sig):
                return False
                
            payload = json.loads(bytes.fromhex(p_bytes).decode())
            if payload["aud"] != expected_target:
                return False
            if payload["exp"] < time.time():
                return False
            if payload["cap"] != required_capability and payload["cap"] != "*":
                return False
            return True
        except Exception:
            return False
