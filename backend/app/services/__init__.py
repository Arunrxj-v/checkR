"""Business-logic services.

Routers stay thin: they validate input, delegate to a service, and shape the
response. All domain rules live here so they are testable without HTTP.
"""

__all__ = [
    "audit_service",
    "auth_service",
    "exam_service",
    "evaluation_service",
    "job_service",
    "processing_service",
    "result_service",
    "review_service",
    "submission_service",
]
