"""TradNex API admin CLI.

    python -m services.api.cli create-user --email me@example.com
    python -m services.api.cli list-users
    python -m services.api.cli revoke-sessions --user-id 1
    python -m services.api.cli show-config
    python -m services.api.cli generate-encryption-key
    python -m services.api.cli import-schwab-token --file ~/schwab_token.json
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from shared.config import settings
from shared.db import get_connection, run_migrations
from shared.services.auth import (
    UserExistsError,
    create_user,
    list_users,
    revoke_all_sessions,
)
from shared.services.credentials import upsert_credential
from shared.services.encryption import EncryptionService
from shared.services.schwab_refresh import REFRESH_TOKEN_LIFETIME_DAYS


def _print_json(obj: Any) -> None:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json")
    print(json.dumps(obj, indent=2, default=str))


async def _cmd_create_user(args: argparse.Namespace) -> None:
    if args.password:
        password = args.password
    else:
        password = getpass.getpass("Password (min 8 chars): ")
        confirm = getpass.getpass("Confirm: ")
        if password != confirm:
            print("Passwords do not match", file=sys.stderr)
            sys.exit(2)
    if len(password) < 8:
        print("Password must be at least 8 characters", file=sys.stderr)
        sys.exit(2)
    conn = get_connection()
    try:
        try:
            user = await create_user(conn, args.email, password)
        except UserExistsError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    finally:
        conn.close()
    if args.json:
        _print_json(user)
        return
    print(f"Created user id={user.id}  email={user.email}")


async def _cmd_list_users(args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        users = await list_users(conn)
    finally:
        conn.close()
    if args.json:
        _print_json([u.model_dump(mode="json") for u in users])
        return
    if not users:
        print("No users seeded yet")
        return
    print(f"{len(users)} user(s):")
    for u in users:
        last = u.last_login_ts.isoformat() if u.last_login_ts else "(never)"
        print(f"  id={u.id}  email={u.email}  last_login={last}")


async def _cmd_revoke_sessions(args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        n = await revoke_all_sessions(conn, args.user_id)
    finally:
        conn.close()
    if args.json:
        _print_json({"revoked": n, "user_id": args.user_id})
        return
    print(f"Revoked {n} active session(s) for user {args.user_id}")


def _cmd_generate_encryption_key(args: argparse.Namespace) -> None:
    """Print a fresh Fernet master key. User adds it to .env as ENCRYPTION_KEY."""
    key = EncryptionService.generate_master_key()
    if args.json:
        _print_json({"encryption_key": key})
        return
    print("# Add the following line to .env (replacing any existing ENCRYPTION_KEY):")
    print(f"ENCRYPTION_KEY={key}")
    print()
    print(
        "# WARNING: rotating this key invalidates every credential row in the "
        "DB.\n# Keep it secret and back it up alongside the .env file."
    )


def _cmd_show_config(args: argparse.Namespace) -> None:
    """Print API config (secrets masked)."""
    safe_keys = {
        "ENVIRONMENT": settings.ENVIRONMENT,
        "API_HOST": settings.API_HOST,
        "API_PORT": settings.API_PORT,
        "DATABASE_PATH": settings.DATABASE_PATH,
        "SESSION_DURATION_DAYS": settings.SESSION_DURATION_DAYS,
        "SESSION_COOKIE_NAME": settings.SESSION_COOKIE_NAME,
        "SESSION_COOKIE_SECURE": settings.SESSION_COOKIE_SECURE,
        "SESSION_COOKIE_SAMESITE": settings.SESSION_COOKIE_SAMESITE,
        "LOGIN_LOCKOUT_THRESHOLD": settings.LOGIN_LOCKOUT_THRESHOLD,
        "LOGIN_LOCKOUT_WINDOW_SECONDS": settings.LOGIN_LOCKOUT_WINDOW_SECONDS,
        "LOGIN_LOCKOUT_DURATION_SECONDS": settings.LOGIN_LOCKOUT_DURATION_SECONDS,
        "CORS_ALLOW_ORIGINS": settings.CORS_ALLOW_ORIGINS or "(none)",
        "DATA_CLIENT": settings.DATA_CLIENT,
        "CLAUDE_CLIENT": settings.CLAUDE_CLIENT,
        "CLAUDE_MODEL": settings.CLAUDE_MODEL,
    }
    if args.json:
        _print_json(safe_keys)
        return
    for k, v in safe_keys.items():
        print(f"  {k:<32} {v}")


def _cmd_import_schwab_token(args: argparse.Namespace) -> None:
    """Import a schwab-py token file into the encrypted DB store.

    Accepts the JSON shape produced by `scripts/schwab_auth.py` (which uses
    schwab-py's `client_from_login_flow`): a top-level dict containing
    `creation_timestamp` and a nested `token` object with `access_token`,
    `refresh_token`, etc.

    Useful for first-time activation when frontend OAuth isn't accessible
    (TrueNAS bootstrap, broken UI, recovery from a corrupted DB row).
    """
    if not settings.ENCRYPTION_KEY:
        print(
            "ENCRYPTION_KEY is not configured. Run "
            "`python -m services.api.cli generate-encryption-key` first.",
            file=sys.stderr,
        )
        sys.exit(2)

    path = Path(args.file).expanduser()
    if not path.exists():
        print(f"Token file not found: {path}", file=sys.stderr)
        sys.exit(2)

    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print(f"Token file is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(2)

    token: dict[str, Any] | None = None
    if isinstance(raw, dict):
        if "token" in raw and isinstance(raw["token"], dict):
            token = raw["token"]
        elif "access_token" in raw and "refresh_token" in raw:
            token = raw

    if not token or "access_token" not in token or "refresh_token" not in token:
        print(
            "Token file missing required keys (access_token, refresh_token). "
            "Expected shape: {token: {access_token, refresh_token, ...}, "
            "creation_timestamp: ...} or {access_token, refresh_token, ...}.",
            file=sys.stderr,
        )
        sys.exit(2)

    now = datetime.now(UTC)
    expires_in = int(token.get("expires_in", 1800))
    expires_at: datetime | None = None
    if isinstance(token.get("expires_at"), int | float):
        expires_at = datetime.fromtimestamp(float(token["expires_at"]), tz=UTC)
    else:
        expires_at = now + timedelta(seconds=expires_in)
    refresh_expires = now + timedelta(days=REFRESH_TOKEN_LIFETIME_DAYS)

    encryption = EncryptionService(settings.ENCRYPTION_KEY)
    conn = get_connection()
    try:
        record = upsert_credential(
            conn,
            encryption,
            "schwab_oauth",
            secrets={
                "access_token": token["access_token"],
                "refresh_token": token["refresh_token"],
                "token_type": token.get("token_type", "Bearer"),
                "scope": token.get("scope", ""),
            },
            expires_at=expires_at,
            refresh_token_expires_at=refresh_expires,
            notes=f"Imported from {path.name}",
        )
    finally:
        conn.close()

    if args.json:
        _print_json(record)
        return
    print(f"Imported Schwab OAuth tokens from {path}")
    print(f"  access_token expires_at:    {expires_at.isoformat()}")
    print(f"  refresh_token expires_at:   {refresh_expires.isoformat()}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="services.api.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cu = sub.add_parser("create-user", help="Create a new login")
    p_cu.add_argument("--email", required=True)
    p_cu.add_argument(
        "--password",
        default=None,
        help="Pass for non-interactive use (testing only)",
    )
    p_cu.add_argument("--json", action="store_true")

    p_lu = sub.add_parser("list-users", help="List users")
    p_lu.add_argument("--json", action="store_true")

    p_rs = sub.add_parser("revoke-sessions", help="Logout all devices for a user")
    p_rs.add_argument("--user-id", type=int, required=True)
    p_rs.add_argument("--json", action="store_true")

    p_sc = sub.add_parser("show-config", help="Print API config (secrets masked)")
    p_sc.add_argument("--json", action="store_true")

    p_gk = sub.add_parser(
        "generate-encryption-key",
        help="Generate a fresh master Fernet key (for ENCRYPTION_KEY in .env)",
    )
    p_gk.add_argument("--json", action="store_true")

    p_ist = sub.add_parser(
        "import-schwab-token",
        help="Import a schwab-py token file into the encrypted credentials store",
    )
    p_ist.add_argument(
        "--file",
        required=True,
        help="Path to the schwab-py JSON token file (e.g. /data/schwab_token.json)",
    )
    p_ist.add_argument("--json", action="store_true")

    return parser


_ASYNC_HANDLERS = {
    "create-user": _cmd_create_user,
    "list-users": _cmd_list_users,
    "revoke-sessions": _cmd_revoke_sessions,
}


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.cmd == "generate-encryption-key":
        # No DB needed; pure key generation.
        _cmd_generate_encryption_key(args)
        return
    run_migrations()
    if args.cmd == "show-config":
        _cmd_show_config(args)
        return
    if args.cmd == "import-schwab-token":
        _cmd_import_schwab_token(args)
        return
    asyncio.run(_ASYNC_HANDLERS[args.cmd](args))


if __name__ == "__main__":
    main()
