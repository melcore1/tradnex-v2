"""Tests for services.api.oauth_state."""

from __future__ import annotations

import time

import pytest

from services.api.oauth_state import (
    OAuthStateInvalid,
    make_state_token,
    verify_state_token,
)
from tests._credential_helpers import get_test_encryption


def test_make_and_verify_round_trip() -> None:
    enc = get_test_encryption()
    token = make_state_token(user_id=42, encryption=enc)
    claims = verify_state_token(token, expected_user_id=42, encryption=enc)
    assert claims.user_id == 42
    assert claims.nonce  # non-empty


def test_token_rejects_wrong_user() -> None:
    enc = get_test_encryption()
    token = make_state_token(user_id=42, encryption=enc)
    with pytest.raises(OAuthStateInvalid, match="user mismatch"):
        verify_state_token(token, expected_user_id=43, encryption=enc)


def test_token_rejects_expired() -> None:
    enc = get_test_encryption()
    issued = time.time() - 7200  # 2h ago
    token = make_state_token(
        user_id=42, encryption=enc, ttl_seconds=600, now=issued
    )
    with pytest.raises(OAuthStateInvalid, match="expired"):
        verify_state_token(token, expected_user_id=42, encryption=enc)


def test_token_rejects_garbled() -> None:
    enc = get_test_encryption()
    with pytest.raises(OAuthStateInvalid, match="decrypt"):
        verify_state_token("not-a-fernet-token", expected_user_id=42, encryption=enc)


def test_token_unique_each_call() -> None:
    enc = get_test_encryption()
    a = make_state_token(user_id=1, encryption=enc)
    b = make_state_token(user_id=1, encryption=enc)
    assert a != b  # Fernet IV + fresh nonce → always different ciphertext
