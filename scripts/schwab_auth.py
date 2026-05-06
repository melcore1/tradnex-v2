"""One-time Schwab OAuth bootstrap.

Usage:
    python scripts/schwab_auth.py

Opens a browser window. Log in to your Schwab BROKERAGE account (not the
developer portal), grant access to your app, and the script captures the
auth code, exchanges it for an access + refresh token, and persists the
token to SCHWAB_TOKEN_PATH (default /data/schwab_token.json).

After this, SchwabDataClient auto-refreshes tokens for as long as the
service stays running. If the refresh window ever lapses (~7 days idle),
re-run this script.
"""

from __future__ import annotations

import sys

from shared.config import settings


def main() -> int:
    if not settings.SCHWAB_CLIENT_ID or not settings.SCHWAB_CLIENT_SECRET:
        print(
            "Schwab credentials not in .env. Add SCHWAB_CLIENT_ID and "
            "SCHWAB_CLIENT_SECRET (and SCHWAB_REDIRECT_URI if non-default), "
            "then re-run.",
            file=sys.stderr,
        )
        return 1

    try:
        from schwab.auth import client_from_login_flow
    except ImportError as e:
        print(f"schwab-py not installed: {e}", file=sys.stderr)
        return 1

    print("Starting Schwab OAuth flow.")
    print(f"  client_id:    {settings.SCHWAB_CLIENT_ID[:6]}...")
    print(f"  redirect_uri: {settings.SCHWAB_REDIRECT_URI}")
    print(f"  token_path:   {settings.SCHWAB_TOKEN_PATH}")
    print()
    print("A browser window will open. Log in to your Schwab BROKERAGE account")
    print("(not developer.schwab.com), grant access, and you'll be redirected.")
    print()

    client_from_login_flow(
        api_key=settings.SCHWAB_CLIENT_ID,
        app_secret=settings.SCHWAB_CLIENT_SECRET,
        callback_url=settings.SCHWAB_REDIRECT_URI,
        token_path=settings.SCHWAB_TOKEN_PATH,
    )

    print()
    print(f"Token saved to {settings.SCHWAB_TOKEN_PATH}")
    print("Set DATA_CLIENT=schwab in .env and restart the data service.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
