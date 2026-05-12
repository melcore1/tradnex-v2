"""MCP tool implementations.

Each module exposes a single async function that takes a sqlite3.Connection
and a MarketDataClient (plus tool-specific args) and returns a JSON-friendly
dict. The dispatcher in `services/mcp/main.py` wraps each in @mcp.tool().
"""
