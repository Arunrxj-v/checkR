"""Seed data for development.

Creates a fully demonstrable examination (Computer Networks — Internal
Examination) with questions, marking schemes, a generated handwritten-style
sample answer sheet, and — when AI_MODE is mock — runs it through the pipeline
so the evaluation workspace is populated immediately after setup.

Idempotent: does nothing if the teacher account already exists.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from decimal import Decimal

from sqlalchemy import func, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.enums import (
    ExamStatus,
    QuestionType,
    UserRole,
)
from app.db.session import get_sessionmaker
from app.models.exam import Exam, MarkingCriterion, Question
from app.services import auth_service

logger = get_logger(__name__)


CN_QUESTIONS: list[dict] = [
    {
        "number": 1,
        "text": "Define the OSI reference model and list its seven layers.",
        "max_marks": 10,
        "question_type": QuestionType.DEFINITION,
        "expected_answer": (
            "The OSI model is a seven-layer conceptual framework: Physical, Data Link, "
            "Network, Transport, Session, Presentation and Application."
        ),
        "keywords": ["OSI", "seven layers", "Physical", "Application"],
        "criteria": [
            ("States that OSI is a layered reference model", 2),
            ("Lists all seven layers correctly", 5),
            ("Explains the purpose of the model", 3),
        ],
    },
    {
        "number": 2,
        "text": (
            "Explain TCP's three-way handshake and why it is required before data "
            "transfer."
        ),
        "max_marks": 5,
        "question_type": QuestionType.EXPLANATION,
        "expected_answer": (
            "The client sends SYN, the server replies SYN-ACK, and the client sends ACK. "
            "It synchronises sequence numbers and confirms both endpoints are reachable."
        ),
        "keywords": ["SYN", "SYN-ACK", "ACK", "sequence numbers"],
        "criteria": [
            ("SYN packet", 1),
            ("SYN-ACK packet", 1),
            ("ACK packet", 1),
            ("Correct sequence/order", 1),
            ("Purpose or explanation", 1),
        ],
    },
    {
        "number": 3,
        "text": (
            "Differentiate between TCP and UDP with respect to reliability, ordering "
            "and connection setup."
        ),
        "max_marks": 8,
        "question_type": QuestionType.EXPLANATION,
        "expected_answer": (
            "TCP is connection-oriented, reliable and ordered; UDP is connectionless, "
            "unreliable and unordered with lower overhead."
        ),
        "keywords": ["connection-oriented", "reliable", "ordered", "overhead"],
        "criteria": [
            ("TCP reliability and acknowledgements", 3),
            ("UDP connectionless behaviour", 3),
            ("Ordering and overhead comparison", 2),
        ],
    },
    {
        "number": 4,
        "text": (
            "A subnet uses the address 192.168.10.0/26. Calculate the number of usable "
            "hosts and the broadcast address. Show your working."
        ),
        "max_marks": 10,
        "question_type": QuestionType.NUMERICAL,
        "expected_answer": (
            "/26 leaves 6 host bits => 2^6 - 2 = 62 usable hosts. Broadcast is "
            "192.168.10.63."
        ),
        "keywords": ["host bits", "usable hosts", "broadcast"],
        "criteria": [
            ("Correct host-bit calculation", 3),
            ("Usable host count (2^n - 2)", 3),
            ("Correct broadcast address", 2),
            ("Clear working shown", 2),
        ],
    },
    {
        "number": 5,
        "text": (
            "Write a program that reverses a singly linked list and state its time "
            "complexity."
        ),
        "max_marks": 12,
        "question_type": QuestionType.PROGRAMMING,
        "expected_answer": (
            "Iteratively reassign next pointers using previous/current/next pointers. "
            "Time O(n), space O(1)."
        ),
        "keywords": ["pointer reversal", "O(n)", "O(1)"],
        "criteria": [
            ("Correct iterative algorithm", 5),
            ("Pointer handling / edge cases", 3),
            ("Correct time complexity", 2),
            ("Correct space complexity", 2),
        ],
    },
]


def _build_sample_script() -> tuple[bytes, list[str], list[list[dict]]]:
    """Generate a handwritten-style sample answer-sheet PDF.

    The content deliberately includes a correct answer, a partially correct
    answer, an answer that *continues onto the next page* and an illegible
    section, so segmentation and the question → page mapping are demonstrable.

    Returns the PDF bytes, the per-page manuscript text and, for each page, a
    normalised (0-1) bounding box per drawn line. The boxes describe where each
    line actually sits on the page, which is what lets the pipeline record
    *which pages an answer appears on* instead of guessing.
    """
    import pymupdf as fitz

    doc = fitz.open()
    pages: list[str] = [
        (
            "DEPARTMENT OF COMPUTER SCIENCE - INTERNAL EXAMINATION 2026\n"
            "CS312 Computer Networks     Roll: 2026-CN-014\n"
            "-----------------------------------------------\n\n"
            "Q1. The OSI model is a reference model for network communication.\n"
            "It divides communication into seven layers.\n"
            "Physical, Data Link, Network, Transport, Session, Presentation, Application.\n"
            "The model makes it easier to design and troubleshoot networks.\n\n"
            "Q2. TCP uses a three way handshake before sending data.\n"
            "The client sends a SYN packet with its sequence number.\n"
        ),
        (
            "The server responds with a SYN-ACK and the client confirms with ACK.\n"
            "Both sides agree on initial sequence numbers before any data is sent.\n\n"
            "Q3. TCP is connection oriented and reliable because every segment\n"
            "is acknowledged. UDP is connectionless and has no acknowledgements.\n"
            "TCP keeps data in order, UDP does not guarantee ordering.\n"
            "UDP has lower overhead and is faster.\n"
        ),
        (
            "Q4. Address 192.168.10.0/26\n"
            "Host bits = 32 - 26 = 6 bits\n"
            "Usable hosts = 2^6 - 2 = 62 hosts\n"
            "Broadcast address = 192.168.10.63\n\n"
            "Q5. def reverse(head):\n"
            "    prev = None\n"
            "    cur = head\n"
            "    while cur:\n"
            "        nxt = cur.next\n"
            "        cur.next = prev\n"
            "        prev = cur\n"
            "        cur = nxt\n"
            "    return prev\n"
            "Time complexity is O(n) as each node is visited once.\n"
            "[illegible] hmm not sure about the rest here\n"
        ),
    ]

    width, height = 595.0, 842.0  # A4
    boxes: list[list[dict]] = []
    for index, text in enumerate(pages, start=1):
        page = doc.new_page(width=width, height=height)
        page_boxes: list[dict] = []
        y = 64.0
        for line in text.splitlines():
            if line.strip():
                page.insert_text((50, y), line, fontsize=11, fontname="helv")
                line_width = fitz.get_text_length(line, fontname="helv", fontsize=11)
                page_boxes.append(
                    {
                        "text": line,
                        "x0": round(50.0 / width, 4),
                        "y0": round((y - 11.0) / height, 4),
                        "x1": round(min(545.0, 50.0 + line_width) / width, 4),
                        "y1": round((y + 4.0) / height, 4),
                    }
                )
                y += 17.0
            else:
                y += 8.0  # paragraph break: visual only, not part of the transcript
        boxes.append(page_boxes)
        page.insert_text(fitz.Point(470, 820), f"Page {index} of {len(pages)}", fontsize=8)

    # The transcript holds the drawn lines only; blank rendering gaps and the
    # footer are not "read" content, so regions and text lines stay 1:1.
    transcripts = [
        "\n".join(box["text"] for box in page_boxes) for page_boxes in boxes
    ]
    return doc.tobytes(), transcripts, boxes


async def _create_sample_submission() -> str | None:
    """Create the demo submission and run it through the pipeline synchronously."""
    from app.ai.factory import get_provider
    from app.ai.validation import validate_ocr
    from app.db.enums import AnswerStatus, PageStatus, SubmissionStatus
    from app.imaging import render_pdf_pages
    from app.models.answer import Answer, AnswerRegion, OCRResult
    from app.models.submission import Submission, SubmissionPage
    from app.prompts.registry import CURRENT_OCR_PROMPT_VERSION
    from app.segmentation import segment_answers
    from app.services import evaluation_service, result_service
    from app.services.page_mapping import resolve_region_page
    from app.storage import KeySpace, build_key, get_storage

    maker = get_sessionmaker()
    async with maker() as db:
        exam = (
            await db.execute(select(Exam).where(Exam.title == "Computer Networks — Internal Examination"))
        ).scalar_one_or_none()
        if exam is None:
            return None
        # An explicit count avoids a lazy relationship load in async context.
        existing_count = (
            await db.execute(
                select(func.count()).select_from(Submission).where(Submission.exam_id == exam.id)
            )
        ).scalar_one()
        if existing_count:
            return None

        submission = Submission(
            exam_id=exam.id,
            student_name="Marcus Vance",
            student_roll="2026-CN-014",
            status=SubmissionStatus.PROCESSING,
            original_filename="marcus-vance-cn312.pdf",
            original_content_type="application/pdf",
        )
        db.add(submission)
        await db.flush()

        storage = get_storage()
        pdf_bytes, page_texts, page_boxes = _build_sample_script()
        original_key = build_key(KeySpace.ORIGINAL, str(submission.id), "source.pdf")
        await storage.save(original_key, pdf_bytes, content_type="application/pdf")
        submission.original_storage_key = original_key
        submission.original_size_bytes = len(pdf_bytes)

        rendered = render_pdf_pages(pdf_bytes)
        submission.page_count = len(rendered)
        for page in rendered:
            key = build_key(KeySpace.PAGES, str(submission.id), f"page_{page.page_number:03d}_original.png")
            await storage.save(key, page.image_bytes, content_type="image/png")
            db.add(
                SubmissionPage(
                    submission_id=submission.id,
                    page_number=page.page_number,
                    original_storage_key=key,
                    width=page.width,
                    height=page.height,
                    status=PageStatus.UPLOADED,
                )
            )
        await db.flush()

        # Preprocess + OCR + store.
        provider = get_provider()
        from app.imaging import preprocess_page

        pages_ocr: list[dict] = []
        for page in (
            await db.execute(
                select(SubmissionPage)
                .where(SubmissionPage.submission_id == submission.id)
                .order_by(SubmissionPage.page_number)
            )
        ).scalars().all():
            raw = await storage.read(page.original_storage_key)
            result = preprocess_page(raw)
            processed_key = build_key(KeySpace.PROCESSED, str(submission.id), f"page_{page.page_number:03d}.jpg")
            thumb_key = build_key(KeySpace.THUMBNAILS, str(submission.id), f"page_{page.page_number:03d}.jpg")
            await storage.save(processed_key, result.processed, content_type="image/jpeg")
            await storage.save(thumb_key, result.thumbnail, content_type="image/jpeg")
            page.processed_storage_key = processed_key
            page.thumbnail_storage_key = thumb_key
            page.deskew_angle = result.deskew_angle
            page.status = PageStatus.OCR_DONE

            ocr_raw = await provider.transcribe_page(
                result.processed,
                page_number=page.page_number,
                prompt_version=CURRENT_OCR_PROMPT_VERSION,
            )
            ocr = validate_ocr(ocr_raw)
            # The manuscript is generated from known text, so use it — together
            # with the boxes the lines were drawn at — as the transcript: the
            # demo stays internally coherent (what the pipeline "reads" matches
            # what is visibly written, and where it is written) while still
            # being produced through the provider abstraction and labelled mock.
            if page.page_number <= len(page_boxes):
                ocr = replace(
                    ocr,
                    text=page_texts[page.page_number - 1].strip(),
                    regions=[
                        {**box, "confidence": ocr.confidence}
                        for box in page_boxes[page.page_number - 1]
                    ],
                )
            db.add(
                OCRResult(
                    page_id=page.id,
                    provider=ocr.provider,
                    model=ocr.model,
                    prompt_version=ocr.prompt_version,
                    text=ocr.text,
                    confidence=ocr.confidence,
                    regions=ocr.regions,
                    raw_response=ocr.raw,
                    is_mock=ocr.is_mock,
                )
            )
            page.ocr_confidence = ocr.confidence
            pages_ocr.append(
                {
                    "page_id": str(page.id),
                    "page_number": page.page_number,
                    "text": ocr.text,
                    "regions": ocr.regions,
                    "confidence": ocr.confidence,
                }
            )
        await db.flush()
        # Mirror the real pipeline's progress counter so the demo data is
        # internally consistent (the UI shows "processed / total" pages).
        submission.processed_page_count = len(pages_ocr)
        await db.flush()

        questions = (
            await db.execute(
                select(Question).where(Question.exam_id == exam.id).order_by(Question.order_index)
            )
        ).scalars().all()
        segmentation = segment_answers(
            pages_ocr, known_question_numbers=[q.number for q in questions]
        )
        submission_pages = (
            await db.execute(
                select(SubmissionPage)
                .where(SubmissionPage.submission_id == submission.id)
                .order_by(SubmissionPage.page_number)
            )
        ).scalars().all()
        page_by_number = {p.page_number: p for p in submission_pages}
        page_by_id = {str(p.id): p for p in submission_pages}

        for index, question in enumerate(questions):
            block = segmentation["answers"].get(question.number)
            transcription = block.transcription if block else ""
            answer = Answer(
                submission_id=submission.id,
                question_id=question.id,
                order_index=index,
                status=AnswerStatus.PENDING,
                transcription=transcription or None,
                ocr_confidence=block.confidence if block else None,
                max_marks=question.max_marks,
                is_handwriting_uncertain=bool(block.boundary_uncertain) if block else True,
                detection_meta={
                    "has_content": bool(transcription.strip()),
                    "source_pages": list(block.page_numbers) if block else [],
                },
            )
            if not transcription.strip():
                answer.is_flagged = True
                answer.flag_reason = "No answer was detected for this question. Verify manually."
            db.add(answer)
            await db.flush()
            if block:
                for region in block.regions:
                    # Resolve the page from the region's own reference; never
                    # default to page 1 (that would fabricate a mapping).
                    page = resolve_region_page(
                        region,
                        pages_by_id=page_by_id,
                        pages_by_number=page_by_number,
                    )
                    if page is None:
                        continue
                    db.add(
                        AnswerRegion(
                            answer_id=answer.id,
                            page_id=page.id,
                            x0=float(region.get("x0", 0.0)),
                            y0=float(region.get("y0", 0.0)),
                            x1=float(region.get("x1", 1.0)),
                            y1=float(region.get("y1", 1.0)),
                            label=(region.get("text") or "")[:120] or None,
                            confidence=region.get("confidence"),
                        )
                    )
        await db.flush()

        # Evaluate every answer with the configured provider (mock by default).
        answers = (
            await db.execute(select(Answer).where(Answer.submission_id == submission.id))
        ).scalars().all()
        for answer in answers:
            question = next(q for q in questions if q.id == answer.question_id)
            try:
                await evaluation_service.evaluate_answer(db, answer=answer, question=question)
            except Exception as exc:
                logger.warning("Seed evaluation skipped for %s: %s", answer.id, exc)

        submission.status = SubmissionStatus.READY_FOR_REVIEW
        await result_service.recompute_submission_totals(db, submission)
        await db.commit()
        return str(submission.id)


async def ensure_demo_data() -> str | None:
    """Ensure the documented demo account and sample data exist.

    This is the single reproducible way the demo credentials are created — the
    teacher goes through ``auth_service.register_user`` exactly like any other
    account, so there is never a manual ``INSERT``. It is safe to run on every
    boot and safe to run against a database that already has other users: the
    demo *account* is guaranteed, while the demo exam and sample submission are
    created once and then left alone.

    Returns a short summary of what was created, or ``None`` if nothing was.
    """
    created: list[str] = []
    maker = get_sessionmaker()

    async with maker() as db:
        # 1. The demo sign-in account (idempotent, provisioned through the
        #    same service the API uses).
        teacher = await auth_service.get_user_by_email(db, settings.seed_teacher_email)
        if teacher is None:
            teacher = await auth_service.register_user(
                db,
                email=settings.seed_teacher_email,
                full_name="Dr. Evelyn Reed",
                password=settings.seed_teacher_password,
                department="Dept. of Computer Science",
                institution="CheckR University",
                role=UserRole.TEACHER,
            )
            await db.commit()
            created.append(f"teacher={teacher.email}")

        # 2. The demo exam, created once for that teacher.
        exam = (
            await db.execute(
                select(Exam)
                .where(Exam.owner_id == teacher.id)
                .where(Exam.title == "Computer Networks — Internal Examination")
            )
        ).scalar_one_or_none()
        if exam is None:
            exam = Exam(
                owner_id=teacher.id,
                title="Computer Networks — Internal Examination",
                subject="Computer Networks",
                subject_code="CS312",
                course="Semester 5",
                academic_year="2026",
                duration_minutes=120,
                instructions="Answer all questions. Show your working for numerical problems.",
                status=ExamStatus.ACTIVE,
            )
            db.add(exam)
            await db.flush()

            total = Decimal("0")
            for index, spec in enumerate(CN_QUESTIONS):
                question = Question(
                    exam_id=exam.id,
                    number=spec["number"],
                    label=f"Q{spec['number']}",
                    text=spec["text"],
                    max_marks=Decimal(str(spec["max_marks"])),
                    question_type=spec["question_type"],
                    expected_answer=spec["expected_answer"],
                    keywords=list(spec["keywords"]),
                    order_index=index,
                )
                db.add(question)
                await db.flush()
                for crit_index, (name, marks) in enumerate(spec["criteria"]):
                    db.add(
                        MarkingCriterion(
                            question_id=question.id,
                            name=name,
                            max_marks=Decimal(str(marks)),
                            order_index=crit_index,
                        )
                    )
                total += Decimal(str(spec["max_marks"]))
            exam.total_marks = total
            await db.commit()
            created.append("exam")

    # 3. The sample submission (second session: it runs the pipeline). Guards on
    #    an existing submission for the exam, so repeated runs are no-ops.
    if created:
        try:
            submission_id = await _create_sample_submission()
            if submission_id:
                created.append("submission")
        except Exception as exc:
            logger.warning("Sample submission could not be generated: %s", exc)

    return ", ".join(created) or None


async def main() -> None:
    result = await ensure_demo_data()
    if result:
        logger.info("Seed complete: %s", result)
    else:
        logger.info("Seed skipped (demo data already present).")


if __name__ == "__main__":
    asyncio.run(main())
