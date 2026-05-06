"""Prompt versioning CRUD + activate/rollback tests."""

from __future__ import annotations

import sqlite3

import pytest

from shared.services.prompts import (
    NoActivePromptError,
    PromptVersionNotFoundError,
    activate_prompt_version,
    create_prompt_version,
    get_active_prompt,
    get_prompt_history,
    get_prompt_version,
    rollback_to_version,
)

_MIN_SCHEMA = {
    "type": "object",
    "required": ["decision"],
    "properties": {"decision": {"type": "string"}},
}


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "p.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


async def test_create_version_starts_pending(db_conn: sqlite3.Connection) -> None:
    v = await create_prompt_version(
        db_conn,
        template_name="entry_evaluation",
        template_text="t1",
        response_schema=_MIN_SCHEMA,
        created_by="alice",
        notes="first revision",
    )
    assert v.status == "pending"
    assert v.notes == "first revision"
    assert v.created_by == "alice"
    # Seed migration creates v1; this should be v2.
    assert v.version_number == 2


async def test_activate_demotes_previous_active(db_conn: sqlite3.Connection) -> None:
    initial = await get_active_prompt(db_conn, "entry_evaluation")
    new = await create_prompt_version(
        db_conn,
        template_name="entry_evaluation",
        template_text="t2",
        response_schema=_MIN_SCHEMA,
        created_by="alice",
    )
    activated = await activate_prompt_version(db_conn, new.id)
    assert activated.status == "active"
    assert activated.activated_ts is not None
    prev = await get_prompt_version(db_conn, initial.id)
    assert prev.status == "deprecated"
    assert prev.deprecated_ts is not None


async def test_activate_idempotent(db_conn: sqlite3.Connection) -> None:
    cur = await get_active_prompt(db_conn, "entry_evaluation")
    again = await activate_prompt_version(db_conn, cur.id)
    assert again.status == "active"
    assert again.id == cur.id


async def test_partial_unique_index_admits_one_active(
    db_conn: sqlite3.Connection,
) -> None:
    """Direct INSERT of a second 'active' row for the same template fails."""
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO prompt_versions ("
            "template_name, version_number, template_text, schema_json, "
            "status, created_ts, created_by"
            ") VALUES ('entry_evaluation', 99, 't', '{}', 'active', "
            "strftime('%s','now'), 'test')"
        )
        db_conn.commit()


async def test_history_newest_first(db_conn: sqlite3.Connection) -> None:
    await create_prompt_version(
        db_conn,
        template_name="entry_evaluation",
        template_text="t2",
        response_schema=_MIN_SCHEMA,
        created_by="alice",
    )
    await create_prompt_version(
        db_conn,
        template_name="entry_evaluation",
        template_text="t3",
        response_schema=_MIN_SCHEMA,
        created_by="alice",
    )
    history = await get_prompt_history(db_conn, "entry_evaluation")
    nums = [v.version_number for v in history]
    assert nums == sorted(nums, reverse=True)


async def test_rollback_to_deprecated_works(db_conn: sqlite3.Connection) -> None:
    initial = await get_active_prompt(db_conn, "entry_evaluation")
    v2 = await create_prompt_version(
        db_conn,
        template_name="entry_evaluation",
        template_text="t2",
        response_schema=_MIN_SCHEMA,
        created_by="alice",
    )
    await activate_prompt_version(db_conn, v2.id)
    # Now v1 is deprecated, v2 is active. Rollback to v1.
    rolled = await rollback_to_version(db_conn, "entry_evaluation", initial.version_number)
    assert rolled.status == "active"
    assert rolled.id == initial.id
    v2_after = await get_prompt_version(db_conn, v2.id)
    assert v2_after.status == "deprecated"


async def test_get_active_raises_when_none(db_conn: sqlite3.Connection) -> None:
    """Wipe the seeded active row, then ensure get_active raises."""
    db_conn.execute("DELETE FROM prompt_versions WHERE template_name='entry_evaluation'")
    db_conn.commit()
    with pytest.raises(NoActivePromptError):
        await get_active_prompt(db_conn, "entry_evaluation")


async def test_get_version_not_found(db_conn: sqlite3.Connection) -> None:
    with pytest.raises(PromptVersionNotFoundError):
        await get_prompt_version(db_conn, 99999)


async def test_notes_preserved_through_activation(db_conn: sqlite3.Connection) -> None:
    v = await create_prompt_version(
        db_conn,
        template_name="entry_evaluation",
        template_text="t",
        response_schema=_MIN_SCHEMA,
        created_by="alice",
        notes="some notes",
    )
    activated = await activate_prompt_version(db_conn, v.id)
    assert activated.notes == "some notes"


async def test_created_by_recorded(db_conn: sqlite3.Connection) -> None:
    v = await create_prompt_version(
        db_conn,
        template_name="exit_evaluation",
        template_text="t",
        response_schema=_MIN_SCHEMA,
        created_by="bob",
    )
    fetched = await get_prompt_version(db_conn, v.id)
    assert fetched.created_by == "bob"
