"""API routers, aggregated under the configured prefix."""

from fastapi import APIRouter

from app.api.routes import answers, auth, exams, results, submissions, system

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(exams.router)
api_router.include_router(submissions.router)
api_router.include_router(answers.router)
api_router.include_router(results.router)
api_router.include_router(system.router)

__all__ = ["api_router"]
