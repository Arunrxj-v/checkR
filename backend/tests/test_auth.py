"""Authentication: registration, login, tokens, refresh, logout, passwords."""

from __future__ import annotations

import pytest

from tests.conftest import TEACHER, auth_header, register_and_login


async def test_register_returns_tokens_and_user(client):
    data = await register_and_login(client)
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["user"]["email"] == TEACHER["email"]
    assert data["user"]["role"] == "teacher"
    # A password must never be echoed back.
    assert "password" not in data["user"]
    assert "hashed_password" not in data["user"]


async def test_password_is_hashed_not_stored_plaintext(client, db):
    from sqlalchemy import select

    from app.models.user import User

    await register_and_login(client)
    user = (await db.execute(select(User))).scalar_one()
    assert user.hashed_password != TEACHER["password"]
    assert user.hashed_password.startswith("$2b$")


async def test_duplicate_email_is_rejected(client):
    await register_and_login(client)
    resp = await client.post("/api/auth/register", json=TEACHER)
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"].lower()


@pytest.mark.parametrize("bad_password", ["short1", "allletters", "12345678"])
async def test_weak_passwords_rejected(client, bad_password):
    payload = {**TEACHER, "password": bad_password}
    resp = await client.post("/api/auth/register", json=payload)
    assert resp.status_code in (400, 422)


async def test_login_success_and_failure(client):
    await register_and_login(client)

    ok = await client.post(
        "/api/auth/login", json={"email": TEACHER["email"], "password": TEACHER["password"]}
    )
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    bad = await client.post(
        "/api/auth/login", json={"email": TEACHER["email"], "password": "Wrong12345"}
    )
    assert bad.status_code == 401

    unknown = await client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "Wrong12345"}
    )
    assert unknown.status_code == 401
    # The same message is returned for both, leaking nothing.
    assert bad.json()["detail"] == unknown.json()["detail"]


async def test_protected_route_requires_token(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


async def test_login_is_rate_limited(client):
    """Brute-force protection: repeated failed logins are throttled."""
    await register_and_login(client)

    statuses = []
    for _ in range(12):
        resp = await client.post(
            "/api/auth/login",
            json={"email": TEACHER["email"], "password": "Wrong12345"},
        )
        statuses.append(resp.status_code)

    assert statuses.count(401) == 10, statuses
    assert statuses[-1] == 429, statuses

    throttled = await client.post(
        "/api/auth/login",
        json={"email": TEACHER["email"], "password": "Wrong12345"},
    )
    assert throttled.status_code == 429
    assert throttled.headers.get("Retry-After")


async def test_invalid_token_rejected(client):
    resp = await client.get("/api/auth/me", headers=auth_header("not-a-real-token"))
    assert resp.status_code == 401


async def test_me_and_update_profile(client):
    data = await register_and_login(client)
    headers = auth_header(data["access_token"])

    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == TEACHER["email"]

    updated = await client.patch(
        "/api/auth/me", json={"full_name": "Prof. Renamed"}, headers=headers
    )
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Prof. Renamed"


async def test_refresh_rotates_tokens(client):
    data = await register_and_login(client)
    resp = await client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert resp.status_code == 200
    new_tokens = resp.json()
    assert new_tokens["access_token"] != data["access_token"]
    assert new_tokens["refresh_token"] != data["refresh_token"]

    # The old refresh token is now revoked (rotation).
    reuse = await client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert reuse.status_code == 401


async def test_access_token_cannot_be_used_as_refresh(client):
    data = await register_and_login(client)
    resp = await client.post("/api/auth/refresh", json={"refresh_token": data["access_token"]})
    assert resp.status_code == 401


async def test_logout_revokes_refresh_token(client):
    data = await register_and_login(client)
    resp = await client.post("/api/auth/logout", json={"refresh_token": data["refresh_token"]})
    assert resp.status_code == 200

    after = await client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert after.status_code == 401


async def test_change_password_invalidates_sessions(client):
    data = await register_and_login(client)
    headers = auth_header(data["access_token"])

    bad = await client.post(
        "/api/auth/password",
        json={"current_password": "Wrong12345", "new_password": "NewPass123"},
        headers=headers,
    )
    assert bad.status_code == 400

    ok = await client.post(
        "/api/auth/password",
        json={"current_password": TEACHER["password"], "new_password": "NewPass123"},
        headers=headers,
    )
    assert ok.status_code == 200

    # Old refresh token has been revoked.
    assert (
        await client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]})
    ).status_code == 401

    login = await client.post(
        "/api/auth/login", json={"email": TEACHER["email"], "password": "NewPass123"}
    )
    assert login.status_code == 200
