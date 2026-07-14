"""Transparent encryption for secrets stored at rest (access tokens, etc.).

Provides an `EncryptedString` SQLAlchemy type: values are encrypted on write and
decrypted on read, so call sites keep using `account.access_token` unchanged.

Key handling:
- The Fernet key is derived from TOKEN_ENCRYPTION_KEY if set, otherwise from the
  app SECRET_KEY (already a stable, persisted secret used for JWTs). No new key to
  manage, and rotating SECRET_KEY is already something the app avoids.
- If no real secret is configured, writing a secret RAISES (fail-loud) so a
  misconfigured deploy never silently stores tokens in plaintext. Set
  ALLOW_PLAINTEXT_TOKENS=true to allow pass-through for local development.

Migration safety: ciphertext is stored with an `enc::` prefix. Legacy plaintext
rows (no prefix) are returned as-is on read and get encrypted the next time they
are written, so existing data keeps working with zero downtime. Run
scripts/encrypt_tokens.py to encrypt existing rows in place.
"""
import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import TypeDecorator, Text

logger = logging.getLogger(__name__)

_PREFIX = "enc::"
_fernet = None
_fernet_ready = False


def _build_fernet():
    key_material = os.getenv("TOKEN_ENCRYPTION_KEY")
    if not key_material:
        try:
            from config import settings
            key_material = getattr(settings, "SECRET_KEY", None)
        except Exception:
            key_material = os.getenv("SECRET_KEY")
    if not key_material or key_material == "fallback-key":
        logger.warning("[crypto] No real secret configured; token encryption is OFF (dev pass-through).")
        return None
    # Derive a valid 32-byte urlsafe-base64 Fernet key from the secret.
    digest = hashlib.sha256(key_material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _get_fernet():
    global _fernet, _fernet_ready
    if not _fernet_ready:
        _fernet = _build_fernet()
        _fernet_ready = True
    return _fernet


def _plaintext_allowed():
    return os.getenv("ALLOW_PLAINTEXT_TOKENS", "false").strip().lower() in ("1", "true", "yes")


def encrypt_value(plaintext):
    """Encrypt a string. Returns it unchanged if already encrypted or not a string.

    Fail-loud: if no encryption key is configured, refuse to store a secret in
    plaintext (raise) unless ALLOW_PLAINTEXT_TOKENS=true is explicitly set for
    local dev. This prevents a misconfigured deploy from silently persisting
    access tokens in the clear, which Meta Platform Terms 6.a forbids.
    """
    if plaintext is None:
        return None
    if not isinstance(plaintext, str) or plaintext.startswith(_PREFIX):
        return plaintext
    f = _get_fernet()
    if f is None:
        if _plaintext_allowed():
            return plaintext
        raise RuntimeError(
            "[crypto] Refusing to store a secret in plaintext: no TOKEN_ENCRYPTION_KEY "
            "or SECRET_KEY is configured. Set one of them, or set ALLOW_PLAINTEXT_TOKENS=true "
            "for local development only."
        )
    return _PREFIX + f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(stored):
    """Decrypt a stored string. Legacy plaintext (no enc:: prefix) is returned as-is."""
    if stored is None:
        return None
    f = _get_fernet()
    if f is None or not isinstance(stored, str) or not stored.startswith(_PREFIX):
        return stored
    try:
        return f.decrypt(stored[len(_PREFIX):].encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error("[crypto] Failed to decrypt a value (wrong key?); returning raw.")
        return stored


class EncryptedString(TypeDecorator):
    """A Text column whose value is encrypted at rest and decrypted transparently."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_value(value)

    def process_result_value(self, value, dialect):
        return decrypt_value(value)
