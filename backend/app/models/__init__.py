"""SQLAlchemy models.

Importing this package registers every model on ``Base.metadata`` — required
for Alembic autogenerate and for ``create_all`` in tests.
"""

from app.models.answer import Answer, AnswerRegion, OCRResult
from app.models.audit import AuditLog
from app.models.evaluation import Evaluation, EvaluationCriterion, TeacherReview
from app.models.exam import Exam, MarkingCriterion, Question
from app.models.job import ProcessingJob
from app.models.submission import Submission, SubmissionPage
from app.models.user import RefreshToken, User

__all__ = [
    "User",
    "RefreshToken",
    "Exam",
    "Question",
    "MarkingCriterion",
    "Submission",
    "SubmissionPage",
    "Answer",
    "AnswerRegion",
    "OCRResult",
    "Evaluation",
    "EvaluationCriterion",
    "TeacherReview",
    "AuditLog",
    "ProcessingJob",
]
