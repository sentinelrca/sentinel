"""Fernet encryption for sensitive config_json fields stored in Postgres.

Usage:
  - encrypt_config(plain_dict)  → {"_enc": "<fernet token>"}
  - decrypt_config(stored_dict) → original dict

Rows written before encryption was introduced (no "_enc" key) are returned
unchanged so the migration is backward-compatible.

Requires SENTINEL_SECRET_KEY env var: a URL-safe base64-encoded 32-byte key.
Generate one with:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet, InvalidToken

_KEY_ENV = "SENTINEL_SECRET_KEY"
_ENC_MARKER = "_enc"

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = os.environ.get(_KEY_ENV)
        if not key:
            raise RuntimeError(
                f"{_KEY_ENV} environment variable is not set. "
                'Generate a key with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
        _fernet = Fernet(key.encode())
    return _fernet


def encrypt_config(data: dict) -> dict:
    """Encrypt a config dict to {_enc: <token>}. Raises if key is not configured."""
    plaintext = json.dumps(data, separators=(",", ":")).encode()
    token = _get_fernet().encrypt(plaintext).decode()
    return {_ENC_MARKER: token}


def decrypt_config(data: dict) -> dict:
    """Decrypt a config dict. Returns unmodified if not encrypted (backward compat)."""
    if _ENC_MARKER not in data:
        return data
    try:
        plaintext = _get_fernet().decrypt(data[_ENC_MARKER].encode())
        return json.loads(plaintext)
    except (InvalidToken, KeyError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to decrypt config_json: {exc}") from exc
