"""The AI provider contract.

Any provider must implement this protocol. The rest of the application depends
only on this interface, so swapping mock -> Gemini -> OpenAI is a configuration
change, never a code change.
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
    ) -> OCRPageResult:
        """Convert a handwritten page image into text (+ confidence/regions)."""
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
    """Raised when a provider fails irrecoverably (bad key, timeout, bad payload)."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable
