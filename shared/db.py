import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from shared.config import settings


def get_connection() -> sqlite3.Connection:
    db_path = Path(settings.DATABASE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def with_transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def run_migrations(migrations_dir: Path | None = None) -> list[str]:
    if migrations_dir is None:
        migrations_dir = Path(__file__).resolve().parent.parent / "migrations"

    conn = get_connection()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _migrations ("
            "filename TEXT PRIMARY KEY, applied_ts REAL NOT NULL)"
        )
        conn.commit()
        existing = {
            row["filename"]
            for row in conn.execute("SELECT filename FROM _migrations")
        }
        applied: list[str] = []
        for path in sorted(migrations_dir.glob("*.sql")):
            if path.name in existing:
                continue
            sql = path.read_text()
            conn.executescript(sql)
            cur = conn.execute(
                "INSERT OR IGNORE INTO _migrations (filename, applied_ts) "
                "VALUES (?, strftime('%s','now'))",
                (path.name,),
            )
            conn.commit()
            if cur.rowcount > 0:
                applied.append(path.name)
        return applied
    finally:
        conn.close()
