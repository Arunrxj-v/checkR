"""Pytest fixtures.

Environment variables are set *before* any application module is imported so
that the cached ``Settings`` singleton picks them up. Tests run against an
in-memory SQLite database (shared via StaticPool) and local file storage in a
temporary directory; the AI provider is the deterministic mock.
"""

from __future__ import annotations

import os
import tempfile

# --- Must happen before importing the app ---------------------------------- #
_TMP = tempfile.mkdtemp(prefix="checkr-tests-")
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DEBUG": "false",
        "DATABASE_URL": "sqlite+aiosqlite://",
        "DATABASE_URL_SYNC": "sqlite://",
        "STORAGE_PATH": _TMP,
        "STORAGE_PROVIDER": "local",
        "AI_PROVIDER": "mock",
        "AI_API_KEY": "",
        "SEED_ON_STARTUP": "false",
        "WORKER_ENABLED": "false",
        "JWT_SECRET": "test-secret-key-for-checkr-tests-only-0123456789",
        "AI_CONFIDENCE_HIGH": "0.85",
        "AI_CONFIDENCE_MEDIUM": "0.60",
        "MAX_UPLOAD_MB": "20",
        # Self-registration is off by default in the product; the suite opts in
        # explicitly so the registration flow stays covered (see test_auth.py).
        "SELF_REGISTRATION_ENABLED": "true",
    }
)

import io  # noqa: E402
import uuid  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402,F401  (register all tables)
from app.db import session as session_module  # noqa: E402
from app.db.base import Base  # noqa: E402


@pytest_asyncio.fixture(scope="function")
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Point the application's session factory at the test engine.
    session_module._engine = eng
    session_module._sessionmaker = async_sessionmaker(
        bind=eng, expire_on_commit=False
    )
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()
    session_module._engine = None
    session_module._sessionmaker = None


@pytest_asyncio.fixture
async def db(engine):
    maker = session_module.get_sessionmaker()
    async with maker() as session:
        yield session


@pytest_asyncio.fixture
async def client(engine):
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Rate limiters are process-wide; clear them so tests stay independent."""
    from app.api import rate_limit

    rate_limit.reset_all()
    yield
    rate_limit.reset_all()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
TEACHER = {
    "email": "teacher@example.com",
    "full_name": "Dr. Test Teacher",
    "password": "Str0ngPass1",
    "department": "Computer Science",
}


async def register_and_login(client: AsyncClient, payload: dict | None = None) -> dict:
    payload = payload or TEACHER
    resp = await client.post("/api/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def teacher_payload() -> dict:
    return dict(TEACHER)


def png_bytes(width: int = 400, height: int = 500, text: str = "") -> bytes:
    """Produce a small PNG to exercise the upload path."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, width - 10, height - 10], outline="black")
    if text:
        for i, line in enumerate(text.splitlines()):
            draw.text((20, 30 + i * 18), line, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def pdf_bytes(pages: list[str]) -> bytes:
    import pymupdf as fitz

    doc = fitz.open()
    for text in pages:
        page = doc.new_page(width=595, height=842)
        page.insert_textbox(fitz.Rect(40, 40, 555, 800), text, fontsize=11)
    return doc.tobytes()


async def create_exam_with_questions(client: AsyncClient, headers: dict) -> dict:
    payload = {
        "title": "Computer Networks — Test",
        "subject": "Computer Networks",
        "subject_code": "CS312",
        "course": "Semester 5",
        "academic_year": "2026",
        "duration_minutes": 90,
        "status": "active",
        "questions": [
            {
                "number": 1,
                "text": "Explain the TCP three-way handshake.",
                "max_marks": 5,
                "question_type": "explanation",
                "expected_answer": "SYN, SYN-ACK, ACK.",
                "keywords": ["SYN", "ACK"],
                "criteria": [
                    {"name": "SYN packet", "max_marks": 1},
                    {"name": "SYN-ACK packet", "max_marks": 1},
                    {"name": "ACK packet", "max_marks": 1},
                    {"name": "Correct sequence", "max_marks": 1},
                    {"name": "Purpose or explanation", "max_marks": 1},
                ],
            },
            {
                "number": 2,
                "text": "Calculate usable hosts for 192.168.10.0/26.",
                "max_marks": 6,
                "question_type": "numerical",
                "criteria": [
                    {"name": "Host bits", "max_marks": 2},
                    {"name": "Usable host count", "max_marks": 2},
                    {"name": "Broadcast address", "max_marks": 2},
                ],
            },
        ],
    }
    resp = await client.post("/api/exams", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


__all__ = [
    "TEACHER",
    "register_and_login",
    "auth_header",
    "png_bytes",
    "pdf_bytes",
    "create_exam_with_questions",
    "uuid",
]
