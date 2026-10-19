"""Result generation, finalisation and exam-level overview routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession, OwnedExam, OwnedSubmission
from app.schemas.answer import SubmissionResult
from app.services import result_service
from app.services.result_service import ResultError

router = APIRouter(tags=["results"])


@router.get("/submissions/{submission_id}/result", response_model=SubmissionResult)
async def submission_result(submission: OwnedSubmission, db: DbSession) -> SubmissionResult:
    result = await result_service.build_result(db, submission)
    return SubmissionResult.model_validate(result)


@router.post("/submissions/{submission_id}/finalize", response_model=SubmissionResult)
async def finalize(
    submission: OwnedSubmission, db: DbSession, user: CurrentUser
) -> SubmissionResult:
    try:
        await result_service.finalize_submission(db, submission=submission, actor=user)
    except ResultError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.flush()
    result = await result_service.build_result(db, submission)
    return SubmissionResult.model_validate(result)


@router.post("/submissions/{submission_id}/reopen", response_model=SubmissionResult)
async def reopen(
    submission: OwnedSubmission, db: DbSession, user: CurrentUser
) -> SubmissionResult:
    await result_service.reopen_submission(db, submission=submission, actor=user)
    await db.flush()
    result = await result_service.build_result(db, submission)
    return SubmissionResult.model_validate(result)


@router.get("/exams/{exam_id}/results")
async def exam_results(exam: OwnedExam, db: DbSession) -> dict:
    return await result_service.exam_result_overview(db, exam.id)


@router.get("/submissions/{submission_id}/progress")
async def submission_progress(submission: OwnedSubmission, db: DbSession) -> dict:
    return await result_service.answer_progress(db, submission.id)
