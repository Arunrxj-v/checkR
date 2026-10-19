"""The demo account must be reproducible from the seed, not by hand.

``python -m app.db.seed`` (and the backend container's start command) call
:func:`app.db.seed.ensure_demo_data`. These tests pin the guarantees the README
makes: the documented credentials exist after seeding, seeding is idempotent, and
it still creates the demo account when the database already holds other users.
"""

from __future__ import annotations

from app.core.config import settings
from app.db.seed import ensure_demo_data


async def _login(client):
    return await client.post(
        "/api/auth/login",
        json={
            "email": settings.seed_teacher_email,
            "password": settings.seed_teacher_password,
        },
    )


async def test_seed_creates_the_documented_demo_account(client, db):
    created = await ensure_demo_data()
    assert created and "teacher=" in created

    resp = await _login(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["email"] == settings.seed_teacher_email
    assert body["user"]["role"] == "teacher"
    assert body["access_token"] and body["refresh_token"]

    me = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == settings.seed_teacher_email


async def test_seed_is_idempotent(client, db):
    assert await ensure_demo_data()
    # A second run has nothing to do and must not duplicate the demo exam.
    assert await ensure_demo_data() is None

    from sqlalchemy import func, select

    from app.models.exam import Exam

    exam_count = (
        await db.execute(
            select(func.count()).select_from(Exam).where(
                Exam.title == "Computer Networks — Internal Examination"
            )
        )
    ).scalar_one()
    assert exam_count == 1
    assert (await _login(client)).status_code == 200


async def test_seed_creates_the_demo_account_alongside_other_users(client, db):
    """An unrelated account must not suppress the demo account."""
    from app.services import auth_service

    await auth_service.register_user(
        db,
        email="someone.else@example.edu",
        full_name="Someone Else",
        password="Str0ngPass1",
    )
    await db.commit()

    created = await ensure_demo_data()
    assert created and "teacher=" in created
    assert (await _login(client)).status_code == 200
