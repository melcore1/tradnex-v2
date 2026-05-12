"""Fernet-signed OAuth state token.

The Schwab OAuth flow needs CSRF protection: a value minted at `/auth/start`
must be verified at `/callback` to confirm that the same browser session
initiated both halves. Production apps usually stash this in a server-side
session, but TradNex 2's auth is DB-backed cookie sessions and has no
`request.session` dict.

We piggyback on the Phase 8a `EncryptionService`: pack `{user_id, nonce, exp}`
into a Fernet token. Anyone holding the token can read its contents only
if they hold the master key — which our server does and Schwab does not.
At `/callback`:
- We decrypt the token (Fernet verifies HMAC, so tampering is rejected).
- We check `exp` hasn't passed (default 10 minutes from issuance).
- We check the embedded `user_id` matches the current session's user.

Replay resistance: the `exp` window is short, and the OAuth flow is
single-user. If multi-user is ever added, swap to a one-time nonce table.
"""

from __future__ import annotations

import secrets
import time

from pydantic import BaseModel

from shared.services.encryption import (
    EncryptionService,
    InvalidEncryptionKeyError,
)

DEFAULT_STATE_TTL_SECONDS = 600  # 10 min


class OAuthStateInvalid(Exception):
    """State token failed verification (expired, wrong user, or malformed)."""


class StateClaims(BaseModel):
    """Decoded contents of a state token."""

    user_id: int
    nonce: str
    exp: float


def make_state_token(
    user_id: int,
    encryption: EncryptionService,
    *,
    ttl_seconds: int = DEFAULT_STATE_TTL_SECONDS,
    now: float | None = None,
) -> str:
    """Mint a fresh state token bound to `user_id`.

    Args:
        user_id: The user starting the OAuth flow.
        encryption: EncryptionService bound to the master key.
        ttl_seconds: How long the token is valid. Default 10 minutes —
            enough for the user to click "Authorize" on Schwab and be
            redirected back.
        now: Override current time (tests).
    """
    issued = now if now is not None else time.time()
    payload = {
        "user_id": user_id,
        "nonce": secrets.token_urlsafe(16),
        "exp": issued + ttl_seconds,
    }
    return encryption.encrypt(payload)


def verify_state_token(
    token: str,
    expected_user_id: int,
    encryption: EncryptionService,
    *,
    now: float | None = None,
) -> StateClaims:
    """Decrypt the token and verify it matches the current user + isn't stale.

    Raises:
        OAuthStateInvalid: when the token is malformed, tampered with,
            expired, or issued for a different user.
    """
    try:
        raw = encryption.decrypt(token)
    except InvalidEncryptionKeyError as exc:
        raise OAuthStateInvalid(
            "State token failed to decrypt (tampered or wrong key)"
        ) from exc

    try:
        claims = StateClaims.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError, ValueError, etc.
        raise OAuthStateInvalid(
            f"State token has unexpected shape: {exc}"
        ) from exc

    current = now if now is not None else time.time()
    if claims.exp < current:
        raise OAuthStateInvalid("State token expired")
    if claims.user_id != expected_user_id:
        raise OAuthStateInvalid(
            "State token user mismatch — was this flow started by another session?"
        )
    return claims
