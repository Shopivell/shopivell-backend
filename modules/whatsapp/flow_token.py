"""
Flow token encoding/decoding for WhatsApp Flows.

The flow_token is a signed, base64-encoded JSON payload that encodes
store_id, phone number, and conversation ID so the data endpoint can
look up the right store without any session state.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Dict

# Max token age: 30 minutes
MAX_TOKEN_AGE = 1800


def _get_secret() -> bytes:
    secret = os.getenv("SECRET_KEY", os.getenv("WHATSAPP_FLOWS_SECRET", "shopivell-default-secret"))
    return secret.encode("utf-8")


def encode_flow_token(store_id: str, phone: str = "", conv_id: str = "") -> str:
    """
    Create a signed flow token.

    Returns a URL-safe base64 string that can be passed as flow_token
    in a WhatsApp Flow message.
    """
    payload = json.dumps({
        "s": str(store_id),
        "p": phone,
        "c": conv_id,
        "t": int(time.time()),
    }, separators=(",", ":"))

    sig = hmac.new(_get_secret(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    raw = f"{payload}|{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_flow_token(token: str) -> Dict[str, str]:
    """
    Decode and verify a flow token.

    Returns {"store_id": ..., "phone": ..., "conv_id": ...}.
    Raises ValueError on invalid or expired tokens.
    """
    try:
        raw = base64.urlsafe_b64decode(token).decode()
    except Exception:
        raise ValueError("Invalid flow token encoding")

    if "|" not in raw:
        raise ValueError("Invalid flow token format")

    payload_str, sig = raw.rsplit("|", 1)
    expected_sig = hmac.new(
        _get_secret(), payload_str.encode(), hashlib.sha256
    ).hexdigest()[:16]

    if not hmac.compare_digest(sig, expected_sig):
        raise ValueError("Invalid flow token signature")

    data = json.loads(payload_str)

    # Check expiry
    token_age = time.time() - data.get("t", 0)
    if token_age > MAX_TOKEN_AGE:
        raise ValueError("Flow token expired")

    return {
        "store_id": data["s"],
        "phone": data.get("p", ""),
        "conv_id": data.get("c", ""),
    }
