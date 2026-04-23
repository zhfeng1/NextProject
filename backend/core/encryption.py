"""Fernet encryption utilities for API Key storage."""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet

from backend.core.config import get_settings


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Lazy-init Fernet instance, cached after first call.

    Using lru_cache instead of module-level initialization so that
    importing this module does not trigger Settings loading — this
    keeps Alembic, tests, and other lightweight imports safe.
    """
    return Fernet(get_settings().fernet_key.encode())


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt an API key. Returns empty string for empty input."""
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext: str) -> str:
    """Decrypt an API key. Returns empty string for empty input.

    Returns empty string if decryption fails (e.g., FERNET_KEY changed),
    preventing API-wide 500 errors from a single bad record.
    """
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except Exception:
        return ""


def mask_api_key(key: str) -> str:
    """Mask an API key for display: 'sk-****abcd' or '****abcd'.

    Returns empty string for empty input, passes through already-masked values.
    """
    if not key or "****" in key:
        return key
    prefix = ""
    dash_pos = key.find("-")
    if 0 < dash_pos <= 10:
        prefix = key[: dash_pos + 1]
    suffix = key[-4:] if len(key) >= 4 else key
    return f"{prefix}****{suffix}"


def is_masked(value: str) -> bool:
    """Check if a value is a masked API key (contains '****')."""
    return bool(value) and "****" in value


__all__ = [
    "decrypt_api_key",
    "encrypt_api_key",
    "is_masked",
    "mask_api_key",
]
