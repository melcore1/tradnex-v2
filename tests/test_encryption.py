"""Tests for shared.services.encryption."""

from __future__ import annotations

import pytest

from shared.services.encryption import (
    EncryptionService,
    InvalidEncryptionKeyError,
    maybe_get_encryption,
)
from tests._credential_helpers import TEST_ENCRYPTION_KEY


def test_roundtrip_dict() -> None:
    enc = EncryptionService(TEST_ENCRYPTION_KEY)
    payload = {"api_key": "abc", "api_secret": "shh", "nested": {"x": 1}}
    ciphertext = enc.encrypt(payload)
    assert ciphertext != ""
    assert "api_key" not in ciphertext  # the plaintext shouldn't be visible
    assert enc.decrypt(ciphertext) == payload


def test_generated_key_works() -> None:
    fresh = EncryptionService.generate_master_key()
    enc = EncryptionService(fresh)
    out = enc.decrypt(enc.encrypt({"x": "y"}))
    assert out == {"x": "y"}


def test_empty_key_rejected() -> None:
    with pytest.raises(InvalidEncryptionKeyError):
        EncryptionService("")


def test_malformed_key_rejected() -> None:
    with pytest.raises(InvalidEncryptionKeyError):
        EncryptionService("not-a-fernet-key")


def test_ciphertext_is_non_deterministic() -> None:
    """Encrypting the same payload twice should produce different
    ciphertexts (Fernet embeds a fresh IV per call). Useful security
    property — guards against attackers identifying duplicate plaintexts
    by ciphertext equality."""
    enc = EncryptionService(TEST_ENCRYPTION_KEY)
    a = enc.encrypt({"x": 1})
    b = enc.encrypt({"x": 1})
    assert a != b
    assert enc.decrypt(a) == enc.decrypt(b)


def test_wrong_key_fails_loudly() -> None:
    """A ciphertext encrypted under one key cannot be decrypted by another."""
    a = EncryptionService(TEST_ENCRYPTION_KEY)
    b = EncryptionService(EncryptionService.generate_master_key())
    ciphertext = a.encrypt({"v": 1})
    with pytest.raises(InvalidEncryptionKeyError):
        b.decrypt(ciphertext)


def test_maybe_get_encryption_with_valid_key(monkeypatch) -> None:
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    import importlib

    from shared import config as cfg

    importlib.reload(cfg)
    enc = maybe_get_encryption()
    assert enc is not None


def test_maybe_get_encryption_missing(monkeypatch) -> None:
    monkeypatch.setenv("ENCRYPTION_KEY", "")
    import importlib

    from shared import config as cfg

    importlib.reload(cfg)
    assert maybe_get_encryption() is None
