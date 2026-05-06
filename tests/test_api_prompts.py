"""/api/prompts tests."""

from __future__ import annotations

import pytest

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


_MIN_SCHEMA = {
    "type": "object",
    "required": ["decision"],
    "properties": {"decision": {"type": "string"}},
}


async def test_show_active_returns_seed(client_setup) -> None:
    _, client = client_setup
    r = client.get("/api/prompts/entry_evaluation/active")
    assert r.status_code == 200
    body = r.json()
    assert body["template_name"] == "entry_evaluation"
    assert body["status"] == "active"
    assert body["version_number"] == 1


async def test_history_includes_v1(client_setup) -> None:
    _, client = client_setup
    r = client.get("/api/prompts/entry_evaluation/history")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 1
    assert body[0]["version_number"] == 1


async def test_create_then_activate(client_setup) -> None:
    _, client = client_setup
    r = client.post(
        "/api/prompts",
        json={
            "template_name": "entry_evaluation",
            "template_text": "v2 template ticker={ticker}",
            "response_schema": _MIN_SCHEMA,
            "notes": "API-created v2",
        },
    )
    assert r.status_code == 201
    v2 = r.json()
    assert v2["status"] == "pending"
    assert v2["version_number"] == 2

    r2 = client.post("/api/prompts/activate", json={"version_id": v2["id"]})
    assert r2.status_code == 200
    assert r2.json()["status"] == "active"

    # v1 is now deprecated
    history = client.get("/api/prompts/entry_evaluation/history").json()
    v1 = next(v for v in history if v["version_number"] == 1)
    assert v1["status"] == "deprecated"


async def test_rollback_reactivates(client_setup) -> None:
    _, client = client_setup
    # create v2 + activate
    v2 = client.post(
        "/api/prompts",
        json={
            "template_name": "entry_evaluation",
            "template_text": "v2 template ticker={ticker}",
            "response_schema": _MIN_SCHEMA,
        },
    ).json()
    client.post("/api/prompts/activate", json={"version_id": v2["id"]})
    r = client.post("/api/prompts/entry_evaluation/rollback/1")
    assert r.status_code == 200
    assert r.json()["version_number"] == 1
    assert r.json()["status"] == "active"


async def test_unknown_template_400(client_setup) -> None:
    _, client = client_setup
    r = client.get("/api/prompts/unknown_template/active")
    assert r.status_code == 400


async def test_activate_unknown_id_404(client_setup) -> None:
    _, client = client_setup
    r = client.post("/api/prompts/activate", json={"version_id": 99999})
    assert r.status_code == 404
