"""
WhatsApp Flows Encryption / Decryption.

Meta requires end-to-end encryption for data endpoints:
  Request:  RSA-OAEP (AES key) + AES-128-GCM (payload)
  Response: AES-128-GCM with flipped IV
"""

import base64
import json
import logging
import os
from typing import Tuple, Dict, Any

from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)


def get_private_key_pem() -> str:
    """Load the RSA private key PEM from environment."""
    pem = os.getenv("WHATSAPP_FLOWS_PRIVATE_KEY", "")
    if not pem:
        raise RuntimeError("WHATSAPP_FLOWS_PRIVATE_KEY env var not set")
    # Handle escaped newlines from env vars
    return pem.replace("\\n", "\n")


def decrypt_request(
    body: Dict[str, str], private_key_pem: str
) -> Tuple[Dict[str, Any], bytes, bytes]:
    """
    Decrypt an incoming WhatsApp Flows data-endpoint request.

    Returns (decrypted_payload, aes_key, iv) — keep aes_key and iv
    to encrypt the response.
    """
    encrypted_aes_key = base64.b64decode(body["encrypted_aes_key"])
    encrypted_flow_data = base64.b64decode(body["encrypted_flow_data"])
    iv = base64.b64decode(body["initial_vector"])

    # 1. Decrypt AES key with RSA-OAEP / SHA-256
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode(), password=None
    )
    aes_key = private_key.decrypt(
        encrypted_aes_key,
        asym_padding.OAEP(
            mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    # 2. Decrypt flow data with AES-128-GCM
    aesgcm = AESGCM(aes_key)
    decrypted = aesgcm.decrypt(iv, encrypted_flow_data, None)
    flow_data: Dict[str, Any] = json.loads(decrypted.decode("utf-8"))

    return flow_data, aes_key, iv


def encrypt_response(
    response: Dict[str, Any], aes_key: bytes, iv: bytes
) -> str:
    """
    Encrypt the response for WhatsApp Flows.

    Uses the same AES key with a flipped IV (each byte XOR 0xFF).
    Returns base64-encoded ciphertext.
    """
    flipped_iv = bytes(b ^ 0xFF for b in iv)

    aesgcm = AESGCM(aes_key)
    plaintext = json.dumps(response).encode("utf-8")
    encrypted = aesgcm.encrypt(flipped_iv, plaintext, None)

    return base64.b64encode(encrypted).decode("utf-8")
