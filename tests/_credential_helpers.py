"""Test helpers for the encrypted credentials store.

Most tests need a stable encryption key + DB-resident credentials. This
module provides:

- TEST_ENCRYPTION_KEY: a deterministic Fernet key (NOT a real secret)
- get_test_encryption(): EncryptionService bound to TEST_ENCRYPTION_KEY
- seed_credential(conn, type, secrets): one-line setup helper

Tests should call seed_credential() rather than monkeypatching env vars
once their factory paths consult the credentials store.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from shared.services.credentials import (
    CredentialType,
    upsert_credential,
)
from shared.services.encryption import EncryptionService

# Deterministic Fernet key (32 bytes base64). NOT a real secret — only used
# in the test suite to keep ciphertext stable across runs.
TEST_ENCRYPTION_KEY = "vJEKnyT7ulyHCYGFY7nBh-XqMhXpwnBJ7-kIPxKj-Rs="


def get_test_encryption() -> EncryptionService:
    return EncryptionService(TEST_ENCRYPTION_KEY)


def seed_credential(
    conn: sqlite3.Connection,
    credential_type: CredentialType,
    secrets: dict[str, Any],
) -> None:
    """Insert an encrypted credential row using the test encryption key."""
    upsert_credential(
        conn,
        get_test_encryption(),
        credential_type,
        secrets=secrets,
        notes="seeded by test helper",
    )
