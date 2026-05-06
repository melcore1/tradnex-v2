"""Prompt version CRUD: create / activate / rollback / history.

Phase 5 stores prompt templates in `prompt_versions` (one row per version,
with status = active | pending | deprecated | archived). The partial
unique index `idx_prompt_one_active` enforces "≤1 active per template" at
the DB level — our activate transaction stays correct even under a
concurrent caller.

Phase 6 will surface CRUD via FastAPI; Phase 5 only ships DB + CLI.
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

TemplateName = Literal["entry_evaluation", "exit_evaluation"]
PromptStatus = Literal["active", "pending", "deprecated", "archived"]


class PromptVersionNotFoundError(LookupError):
    """Version id (or template + version_number) doesn't exist."""


class NoActivePromptError(LookupError):
    """The given template has no row in 'active' status."""


class PromptVersion(BaseModel):
    """One row from prompt_versions."""

    model_config = ConfigDict(frozen=True)

    id: int
    template_name: TemplateName
    version_number: int
    template_text: str
    response_schema: dict[str, Any]
    status: PromptStatus
    created_ts: datetime
    created_by: str
    activated_ts: datetime | None = None
    deprecated_ts: datetime | None = None
    notes: str | None = None


def _row_to_version(row: sqlite3.Row) -> PromptVersion:
    return PromptVersion(
        id=int(row["id"]),
        template_name=row["template_name"],
        version_number=int(row["version_number"]),
        template_text=row["template_text"],
        response_schema=json.loads(row["schema_json"]),
        status=row["status"],
        created_ts=datetime.fromtimestamp(float(row["created_ts"]), tz=UTC),
        created_by=row["created_by"],
        activated_ts=(
            datetime.fromtimestamp(float(row["activated_ts"]), tz=UTC)
            if row["activated_ts"] is not None
            else None
        ),
        deprecated_ts=(
            datetime.fromtimestamp(float(row["deprecated_ts"]), tz=UTC)
            if row["deprecated_ts"] is not None
            else None
        ),
        notes=row["notes"],
    )


_COLS = (
    "id, template_name, version_number, template_text, schema_json, "
    "status, created_ts, created_by, activated_ts, deprecated_ts, notes"
)


async def get_active_prompt(
    conn: sqlite3.Connection,
    template_name: TemplateName,
) -> PromptVersion:
    row = conn.execute(
        f"SELECT {_COLS} FROM prompt_versions "
        "WHERE template_name = ? AND status = 'active'",
        (template_name,),
    ).fetchone()
    if row is None:
        raise NoActivePromptError(
            f"No active prompt for template '{template_name}'"
        )
    return _row_to_version(row)


async def get_prompt_version(
    conn: sqlite3.Connection,
    version_id: int,
) -> PromptVersion:
    row = conn.execute(
        f"SELECT {_COLS} FROM prompt_versions WHERE id = ?",
        (version_id,),
    ).fetchone()
    if row is None:
        raise PromptVersionNotFoundError(
            f"prompt_versions row id={version_id} not found"
        )
    return _row_to_version(row)


async def get_prompt_by_number(
    conn: sqlite3.Connection,
    template_name: TemplateName,
    version_number: int,
) -> PromptVersion:
    row = conn.execute(
        f"SELECT {_COLS} FROM prompt_versions "
        "WHERE template_name = ? AND version_number = ?",
        (template_name, version_number),
    ).fetchone()
    if row is None:
        raise PromptVersionNotFoundError(
            f"Template '{template_name}' has no version {version_number}"
        )
    return _row_to_version(row)


async def create_prompt_version(
    conn: sqlite3.Connection,
    *,
    template_name: TemplateName,
    template_text: str,
    response_schema: dict[str, Any],
    created_by: str,
    notes: str | None = None,
) -> PromptVersion:
    """Create a new version in 'pending' status. version_number auto-assigns
    to max+1 for that template."""
    row = conn.execute(
        "SELECT COALESCE(MAX(version_number), 0) AS m FROM prompt_versions "
        "WHERE template_name = ?",
        (template_name,),
    ).fetchone()
    next_num = int(row["m"]) + 1
    now_ts = time.time()
    cur = conn.execute(
        "INSERT INTO prompt_versions ("
        "template_name, version_number, template_text, schema_json, "
        "status, created_ts, created_by, notes"
        ") VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
        (
            template_name,
            next_num,
            template_text,
            json.dumps(response_schema),
            now_ts,
            created_by,
            notes,
        ),
    )
    conn.commit()
    new_id = cur.lastrowid
    if new_id is None:
        raise RuntimeError("Failed to insert prompt_versions row")
    return await get_prompt_version(conn, int(new_id))


async def activate_prompt_version(
    conn: sqlite3.Connection,
    version_id: int,
) -> PromptVersion:
    """Promote a pending or deprecated version to active. Demote the
    previously-active row to deprecated. Atomic.
    """
    target = await get_prompt_version(conn, version_id)
    if target.status == "active":
        return target

    now_ts = time.time()
    try:
        conn.execute("BEGIN")
        conn.execute(
            "UPDATE prompt_versions SET status = 'deprecated', "
            "deprecated_ts = ? WHERE template_name = ? AND status = 'active'",
            (now_ts, target.template_name),
        )
        conn.execute(
            "UPDATE prompt_versions SET status = 'active', activated_ts = ? "
            "WHERE id = ?",
            (now_ts, version_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return await get_prompt_version(conn, version_id)


async def rollback_to_version(
    conn: sqlite3.Connection,
    template_name: TemplateName,
    target_version_number: int,
) -> PromptVersion:
    """Activate a (likely deprecated) version by version_number. Same atomic
    swap as activate_prompt_version."""
    target = await get_prompt_by_number(conn, template_name, target_version_number)
    return await activate_prompt_version(conn, target.id)


async def get_prompt_history(
    conn: sqlite3.Connection,
    template_name: TemplateName,
) -> list[PromptVersion]:
    """All versions of a template, newest first."""
    rows = conn.execute(
        f"SELECT {_COLS} FROM prompt_versions WHERE template_name = ? "
        "ORDER BY version_number DESC",
        (template_name,),
    ).fetchall()
    return [_row_to_version(r) for r in rows]
