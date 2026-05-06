"""/api/candidates tests."""

from __future__ import annotations

import json
import time

import pytest

from services.scanner.persistence import persist_candidate
from tests._api_helpers import build_test_client, reset_modules_for_test_db, seed_user


@pytest.fixture
async def client_setup(tmp_path, monkeypatch):
    conn = reset_modules_for_test_db(tmp_path, monkeypatch)
    await seed_user(conn)
    client = build_test_client()
    client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "testpass1234"},
    )
    yield conn, client
    conn.close()


async def _seed_pending_human(conn) -> int:
    from tests.fixtures.strategy_fixtures import build_long_call_candidate

    cand = await build_long_call_candidate()
    cid = await persist_candidate(conn, cand)
    conn.execute(
        "UPDATE candidates SET status = 'pending_human_approval' WHERE id = ?",
        (cid,),
    )
    conn.commit()
    return cid


async def test_list_returns_recent(client_setup) -> None:
    conn, client = client_setup
    cid = await _seed_pending_human(conn)
    r = client.get("/api/candidates")
    assert r.status_code == 200
    body = r.json()
    assert any(c["id"] == cid for c in body)


async def test_list_filters_by_status(client_setup) -> None:
    conn, client = client_setup
    await _seed_pending_human(conn)
    # Make a second one and reject it
    cid2 = await _seed_pending_human(conn)
    conn.execute(
        "UPDATE candidates SET status='rejected_by_user' WHERE id=?", (cid2,)
    )
    conn.commit()
    r = client.get("/api/candidates?status=rejected_by_user")
    assert r.status_code == 200
    body = r.json()
    assert all(c["status"] == "rejected_by_user" for c in body)


async def test_get_detail_returns_copyable(client_setup) -> None:
    conn, client = client_setup
    cid = await _seed_pending_human(conn)
    r = client.get(f"/api/candidates/{cid}")
    assert r.status_code == 200
    body = r.json()
    assert body["candidate"]["id"] == cid
    assert "copyable_text" in body
    assert body["copyable_text"].startswith("# Candidate")


async def test_approve_transitions_status(client_setup) -> None:
    conn, client = client_setup
    cid = await _seed_pending_human(conn)
    r = client.post(f"/api/candidates/{cid}/approve", json={"notes": "lgtm"})
    assert r.status_code == 200
    body = r.json()
    assert body["new_status"] == "approved"
    row = conn.execute(
        "SELECT status, overrides_applied_json FROM candidates WHERE id=?", (cid,)
    ).fetchone()
    assert row["status"] == "approved"
    overrides = json.loads(row["overrides_applied_json"])
    assert overrides.get("approval_notes") == "lgtm"


async def test_approve_idempotent(client_setup) -> None:
    conn, client = client_setup
    cid = await _seed_pending_human(conn)
    client.post(f"/api/candidates/{cid}/approve", json={})
    r = client.post(f"/api/candidates/{cid}/approve", json={})
    assert r.status_code == 200
    assert r.json()["already_processed"] is True


async def test_approve_wrong_state_409(client_setup) -> None:
    conn, client = client_setup
    cid = await _seed_pending_human(conn)
    conn.execute(
        "UPDATE candidates SET status = 'rejected_by_user' WHERE id=?", (cid,)
    )
    conn.commit()
    r = client.post(f"/api/candidates/{cid}/approve", json={})
    assert r.status_code == 409


async def test_approve_missing_404(client_setup) -> None:
    _, client = client_setup
    r = client.post("/api/candidates/99999/approve", json={})
    assert r.status_code == 404


async def test_reject_transitions_status(client_setup) -> None:
    conn, client = client_setup
    cid = await _seed_pending_human(conn)
    r = client.post(
        f"/api/candidates/{cid}/reject",
        json={"reason": "macro headwinds", "notes": "skip this one"},
    )
    assert r.status_code == 200
    assert r.json()["new_status"] == "rejected_by_user"
    row = conn.execute(
        "SELECT status FROM candidates WHERE id=?", (cid,)
    ).fetchone()
    assert row["status"] == "rejected_by_user"


# ---- Phase 7: /full-context ----


async def test_full_context_returns_copyable_text(client_setup) -> None:
    """/full-context returns just the copyable_text payload."""
    conn, client = client_setup
    cid = await _seed_pending_human(conn)
    r = client.get(f"/api/candidates/{cid}/full-context")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"copyable_text"}
    assert body["copyable_text"].startswith("# Candidate")
    # Same text the detail endpoint would return.
    detail = client.get(f"/api/candidates/{cid}").json()
    assert body["copyable_text"] == detail["copyable_text"]


async def test_full_context_404_on_missing(client_setup) -> None:
    _, client = client_setup
    r = client.get("/api/candidates/99999/full-context")
    assert r.status_code == 404


# Suppress unused-import noise (time is for future tests if needed)
_ = time
