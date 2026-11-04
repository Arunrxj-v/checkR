"""The AI provider contract.

Any provider must implement this protocol. The rest of the application depends
only on this interface, so swapping providers is a configuration change, never
a code change. CheckR's production workflow runs on the local Ollama provider
(``AI_PROVIDER=ollama``).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.ai.types import AnswerEvaluationResult, EvaluationContext, OCRPageResult


@runtime_checkable
class AIProvider(Protocol):
    """Capabilities CheckR requires from a vision/language provider."""

    name: str
    model: str
    is_mock: bool

    async def transcribe_page(
        self,
        image_bytes: bytes,
        *,
        page_number: int,
        prompt_version: str = "handwriting_v1",
        previous_context: str | None = None,
    ) -> OCRPageResult:
        """Convert a handwritten page image into text (+ confidence/regions).

        ``previous_context`` carries the tail of the previous page's
        transcription so multi-page answers can be recognised as continuations.
        """
        ...

    async def evaluate_answer(
        self,
        context: EvaluationContext,
        *,
        prompt_version: str,
    ) -> AnswerEvaluationResult:
        """Grade one answer against one question's marking scheme."""
        ...

    async def health(self) -> dict:
        """Cheap liveness/authenticity check for the settings screen."""
        ...

    async def aclose(self) -> None:
        """Release any network resources."""
        ...


class AIProviderError(Exception):
    """Raised when a provider fails irrecoverably (bad key, timeout, bad payload).

    ``kind`` classifies the failure so callers can surface an actionable
    message instead of a generic one:

    * ``unavailable``    — the inference runtime cannot be reached
    * ``model_missing``  — the configured model is not installed
    * ``timeout``        — the request exceeded the configured timeout
    * ``bad_response``   — the model returned unusable output (after retries)
    * ``config``         — a configuration problem (missing key, disabled, …)
    * ``""``             — uncategorised
    """

    def __init__(self, message: str, *, retryable: bool = True, kind: str = "") -> None:
        super().__init__(message)
        self.retryable = retryable
        self.kind = kind
