"""Answer-sheet upload, validation, access control and page retrieval."""

from __future__ import annotations

from tests.conftest import (
    auth_header,
    create_exam_with_questions,
    pdf_bytes,
    png_bytes,
    register_and_login,
)


async def _setup(client):
    data = await register_and_login(client)
    headers = auth_header(data["access_token"])
    exam = await create_exam_with_questions(client, headers)
    return headers, exam


async def test_upload_single_image_creates_submission(client):
    headers, exam = await _setup(client)
    resp = await client.post(
        f"/api/exams/{exam['id']}/submissions",
        files={"files": ("script.png", png_bytes(), "image/png")},
        data={"student_name": "Ada Lovelace", "student_roll": "2026-CS-001"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body) == 1
    submission = body[0]
    assert submission["student_name"] == "Ada Lovelace"
    assert submission["student_roll"] == "2026-CS-001"
    assert submission["status"] == "uploaded"
    # The original filename is retained for reference.
    assert submission["original_filename"] == "script.png"


async def test_upload_multi_page_pdf(client):
    headers, exam = await _setup(client)
    pages = ["Q1. Answer one.", "Q2. Answer two.", "Q3. Answer three."]
    resp = await client.post(
        f"/api/exams/{exam['id']}/submissions",
        files={"files": ("bundle.pdf", pdf_bytes(pages), "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()[0]["status"] == "uploaded"


async def test_multiple_files_create_multiple_submissions(client):
    headers, exam = await _setup(client)
    resp = await client.post(
        f"/api/exams/{exam['id']}/submissions",
        files=[
            ("files", ("ada_lovelace.png", png_bytes(), "image/png")),
            ("files", ("alan_turing.png", png_bytes(), "image/png")),
        ],
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body) == 2
    # Names are derived from filenames when no explicit name is supplied.
    assert {s["student_name"] for s in body} == {"Ada Lovelace", "Alan Turing"}


async def test_rejects_unsupported_file_type(client):
    headers, exam = await _setup(client)
    resp = await client.post(
        f"/api/exams/{exam['id']}/submissions",
        files={"files": ("notes.txt", b"just some text", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "Unsupported" in resp.json()["detail"]


async def test_rejects_empty_file(client):
    headers, exam = await _setup(client)
    resp = await client.post(
        f"/api/exams/{exam['id']}/submissions",
        files={"files": ("empty.png", b"", "image/png")},
        headers=headers,
    )
    assert resp.status_code == 400


async def test_rejects_file_with_mismatched_content_type(client):
    """A .png filename carrying PDF bytes is accepted only if it really is a PDF."""
    headers, exam = await _setup(client)
    resp = await client.post(
        f"/api/exams/{exam['id']}/submissions",
        files={"files": ("fake.pdf", png_bytes(), "application/pdf")},
        headers=headers,
    )
    # Magic bytes say PNG, declared type says PDF -> the sniffed type wins and
    # the declared type is rejected as inconsistent.
    assert resp.status_code == 400


async def test_upload_enqueues_processing_job(client):
    headers, exam = await _setup(client)
    resp = await client.post(
        f"/api/exams/{exam['id']}/submissions",
        files={"files": ("script.png", png_bytes(), "image/png")},
        headers=headers,
    )
    submission_id = resp.json()[0]["id"]

    jobs = await client.get(f"/api/submissions/{submission_id}/jobs", headers=headers)
    assert jobs.status_code == 200
    assert any(j["job_type"] == "process_submission" for j in jobs.json())


async def test_submission_is_private_to_exam_owner(client):
    headers, exam = await _setup(client)
    resp = await client.post(
        f"/api/exams/{exam['id']}/submissions",
        files={"files": ("script.png", png_bytes(), "image/png")},
        headers=headers,
    )
    submission_id = resp.json()[0]["id"]

    other = await register_and_login(
        client,
        {"email": "intruder@example.com", "full_name": "Intruder", "password": "Str0ngPass9"},
    )
    other_headers = auth_header(other["access_token"])

    assert (
        await client.get(f"/api/submissions/{submission_id}", headers=other_headers)
    ).status_code == 404
    assert (
        await client.get(f"/api/submissions/{submission_id}/status", headers=other_headers)
    ).status_code == 404


async def test_list_submissions_scoped_to_owner(client):
    headers, exam = await _setup(client)
    await client.post(
        f"/api/exams/{exam['id']}/submissions",
        files={"files": ("a.png", png_bytes(), "image/png")},
        headers=headers,
    )

    listing = await client.get("/api/submissions", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    other = await register_and_login(
        client,
        {"email": "second@example.com", "full_name": "Second", "password": "Str0ngPass3"},
    )
    other_listing = await client.get(
        "/api/submissions", headers=auth_header(other["access_token"])
    )
    assert other_listing.json()["total"] == 0


async def test_image_endpoint_requires_authorisation(client):
    headers, exam = await _setup(client)
    resp = await client.post(
        f"/api/exams/{exam['id']}/submissions",
        files={"files": ("script.png", png_bytes(), "image/png")},
        headers=headers,
    )
    submission_id = resp.json()[0]["id"]

    # No auth at all.
    unauthenticated = await client.get(f"/api/submissions/{submission_id}/pages")
    assert unauthenticated.status_code == 401
