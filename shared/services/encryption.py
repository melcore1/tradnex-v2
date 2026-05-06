"""Symmetric encryption for credentials at rest.

Wraps `cryptography.fernet.Fernet` with a JSON-aware interface. The master
key is a base64-encoded 32-byte value provided via the `ENCRYPTION_KEY`
environment variable (see `Settings.ENCRYPTION_KEY`).

Generate a new key for first-time setup:

    python -m services.api.cli generate-encryption-key

If the master key changes, all existing rows in the `credentials` table
become unreadable; treat key rotation as a credential re-entry event.
"""

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class EncryptionError(Exception):
    """Generic encryption-layer failure."""


class InvalidEncryptionKeyError(EncryptionError):
    """Raised when ENCRYPTION_KEY is missing, malformed, or fails to decrypt
    a value. Most often this means the key was rotated and the existing
    ciphertext was encrypted with the previous key."""


class EncryptionService:
    """Symmetric encryption wrapper for JSON-serializable secrets.

    Use `encrypt(dict)` / `decrypt(str)`. The cipher is non-deterministic:
    encrypting the same plaintext twice yields different ciphertexts (Fernet
    embeds a fresh IV per call). Useful security property; tests must compare
    via decrypt rather than ciphertext equality.
    """

    def __init__(self, master_key: str) -> None:
        if not master_key:
            raise InvalidEncryptionKeyError(
                "ENCRYPTION_KEY is empty. Generate one via "
                "`python -m services.api.cli generate-encryption-key` "
                "and add it to .env."
            )
        try:
            self._fernet = Fernet(master_key.encode("ascii"))
        except (ValueError, TypeError) as e:
            raise InvalidEncryptionKeyError(
                f"ENCRYPTION_KEY is not a valid Fernet key: {e}. "
                "Regenerate via `python -m services.api.cli "
                "generate-encryption-key`."
            ) from e

    def encrypt(self, data: dict[str, Any]) -> str:
        """Serialize `data` to JSON, encrypt, return base64 ciphertext."""
        plaintext = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return self._fernet.encrypt(plaintext).decode("ascii")

    def decrypt(self, ciphertext: str) -> dict[str, Any]:
        """Decrypt base64 ciphertext to a dict.

        Raises:
            InvalidEncryptionKeyError: if the ciphertext was produced with a
                different key (likely after key rotation) or is corrupted.
        """
        try:
            plaintext = self._fernet.decrypt(ciphertext.encode("ascii"))
        except InvalidToken as e:
            raise InvalidEncryptionKeyError(
                "Failed to decrypt credential. The ENCRYPTION_KEY may have "
                "rotated; re-enter the credential via the UI or rotate the "
                "key back."
            ) from e
        loaded = json.loads(plaintext)
        if not isinstance(loaded, dict):
            raise InvalidEncryptionKeyError(
                f"Decrypted credential is not a JSON object: {type(loaded).__name__}"
            )
        return loaded

    @classmethod
    def generate_master_key(cls) -> str:
        """Produce a fresh Fernet key (base64-encoded 32 bytes)."""
        return Fernet.generate_key().decode("ascii")


def maybe_get_encryption() -> EncryptionService | None:
    """Construct an `EncryptionService` from `Settings.ENCRYPTION_KEY`.

    Returns None when the key isn't configured or is malformed. Used by
    long-running services so they can pass `encryption=` to the
    credentials-aware factories without conditional boilerplate per call site.
    """
    from shared.config import settings as _settings

    key = _settings.ENCRYPTION_KEY
    if not key:
        return None
    try:
        return EncryptionService(key)
    except InvalidEncryptionKeyError:
        return None
