"""Deterministic mock AI provider.

Purpose: let the entire workflow (OCR -> segmentation -> evaluation -> review)
run end-to-end with zero network calls and zero cost, while remaining
*predictable* so tests can assert exact outcomes.

Every output is derived from a stable hash of the input, so the same page or
answer always yields the same result. Mock results are always labelled
``is_mock=True`` and the UI distinguishes them from real AI output.
"""

from __future__ import annotations

import hashlib
import textwrap

from app.ai.base import AIProviderError
from app.ai.types import (
    AnswerEvaluationResult,
    CriterionOutcome,
    EvaluationContext,
    OCRPageResult,
)

_PROVIDER_NAME = "mock"
_MODEL_NAME = "checkr-mock-vision"

# Realistic-looking handwritten transcriptions used to seed the demo. Chosen by
# a stable hash so a given page always transcribes the same way.
_TRANSCRIPTION_POOL = [
    textwrap.dedent(
        """\
        Definition: The algorithm processes the input in a single pass.
        The time complexity is O(n log n) because the input is divided into
        halves and each level of recursion performs a linear merge.
        Space complexity is O(n) for the auxiliary buffer.
        """
    ),
    textwrap.dedent(
        """\
        The three-way handshake proceeds as follows:
        1. The client sends a SYN segment with a random sequence number.
        2. The server replies with SYN-ACK acknowledging the client.
        3. The client sends ACK, after which the connection is established.
        """
    ),
    textwrap.dedent(
        """\
        Balance factor is defined as Height(Left) - Height(Right).
        For an AVL tree the balance factor must remain in {-1, 0, +1}.
        Rotations restore this invariant in O(1) pointer changes.
        """
    ),
    textwrap.dedent(
        """\
        Given: mass m = 5 kg, acceleration a = 2 m/s^2.
        Using Newton's second law, F = m * a = 5 * 2 = 10 N.
        Therefore the net force acting on the body is 10 newtons.
        """
    ),
    textwrap.dedent(
        """\
        A hash table resolves collisions using chaining or open addressing.
        With double hashing, the probe sequence is h(k, i) = (h1(k) + i*h2(k)) mod m.
        This reduces clustering compared to linear probing.
        """
    ),
]


def _stable_seed(*parts: object) -> int:
    """A process-stable integer seed derived from the given parts."""
    joined = "\u0000".join(str(p) for p in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _pick(seq: list, seed: int):
    return seq[seed % len(seq)]


class MockProvider:
    """Offline provider implementing the :class:`AIProvider` protocol."""

    name = _PROVIDER_NAME
    model = _MODEL_NAME
    is_mock = True

    def __init__(self, *, seed_salt: str = "") -> None:
        self._salt = seed_salt

    # ------------------------------------------------------------------ #
    # OCR / transcription
    # ------------------------------------------------------------------ #
    async def transcribe_page(
        self,
        image_bytes: bytes,
        *,
        page_number: int,
        prompt_version: str = "handwriting_v1",
    ) -> OCRPageResult:
        if not image_bytes:
            raise AIProviderError("Empty page image supplied to OCR.", retryable=False)

        seed = _stable_seed(self._salt, page_number, len(image_bytes), image_bytes[:64])
        text = _pick(_TRANSCRIPTION_POOL, seed)

        # Confidence spread 0.55 - 0.96 so flagging paths are exercised.
        confidence = round(0.55 + (seed % 42) / 100.0, 2)

        # Occasionally simulate an illegible page: the provider refuses to guess.
        if confidence < 0.62:
            text = (
                "[MOCK OCR] Some handwriting on this page could not be read "
                "confidently. Manual review recommended."
            )

        regions = [
            {
                "text": line,
                "x0": 0.10,
                "y0": round(0.15 + i * 0.06, 3),
                "x1": 0.90,
                "y1": round(0.20 + i * 0.06, 3),
                "confidence": confidence,
            }
            for i, line in enumerate(text.splitlines())
            if line.strip()
        ]

        return OCRPageResult(
            text=text.strip(),
            confidence=confidence,
            regions=regions,
            raw={"mock": True, "seed": seed, "page_number": page_number},
            model=self.model,
            provider=self.name,
            prompt_version=prompt_version,
            is_mock=True,
        )

    # ------------------------------------------------------------------ #
    # Evaluation
    # ------------------------------------------------------------------ #
    async def evaluate_answer(
        self,
        context: EvaluationContext,
        *,
        prompt_version: str,
    ) -> AnswerEvaluationResult:
        criteria = context.criteria or [
            {"name": "Overall answer", "description": None, "max_marks": context.max_marks}
        ]

        outcomes: list[CriterionOutcome] = []
        strengths: list[str] = []
        gaps: list[str] = []
        contradictions: list[str] = []
        flags: list[str] = []

        base_seed = _stable_seed(
            self._salt,
            context.submission_ref,
            context.question_label,
            context.question_text,
            context.transcription[:200],
        )

        total_awarded = 0.0
        for idx, crit in enumerate(criteria):
            name = str(crit.get("name", f"Criterion {idx + 1}"))
            max_marks = float(crit.get("max_marks", 0) or 0)
            seed = _stable_seed(base_seed, idx, name)
            roll = seed % 100

            if roll < 62:
                awarded = max_marks
                satisfied = True
                comment = "Clearly addressed."
                strengths.append(name)
            elif roll < 84:
                awarded = round(max_marks * 0.5, 1)
                satisfied = True
                comment = "Partially addressed; some detail missing."
                strengths.append(name)
                gaps.append(f"{name}: partial coverage")
            else:
                awarded = 0.0
                satisfied = False
                comment = "Not found in the response."
                gaps.append(f"{name}: not addressed")

            # Detect an (un)seldom contradiction to exercise that pathway.
            if seed % 37 == 0 and awarded == 0.0:
                contradictions.append(f"{name}: appears to contradict the expected approach")

            outcomes.append(
                CriterionOutcome(
                    name=name,
                    max_marks=max_marks,
                    awarded_marks=awarded,
                    satisfied=satisfied,
                    comment=comment,
                )
            )
            total_awarded += awarded

        # Clamp to the question maximum.
        total_awarded = min(total_awarded, context.max_marks)

        # Confidence: higher when OCR was confident and the transcription is substantial.
        ocr = context.ocr_confidence if context.ocr_confidence is not None else 0.8
        length_factor = min(len(context.transcription) / 400.0, 1.0)
        confidence = round(0.55 + 0.28 * ocr + 0.14 * length_factor, 2)
        confidence = max(0.0, min(1.0, confidence))

        if confidence < 0.62:
            flags.append("Low confidence — handwriting or response quality is unclear.")
        if context.images and len(context.images) == 0:  # defensive, never true
            flags.append("No answer image available for cross-checking.")

        ratio = total_awarded / context.max_marks if context.max_marks else 0.0
        if ratio >= 0.95:
            summary = "Complete and accurate response covering all marking criteria."
        elif ratio >= 0.6:
            summary = (
                "Largely correct response; some marking criteria are only "
                "partially satisfied."
            )
        elif ratio > 0:
            summary = (
                "Partial response — several key marking criteria are missing or "
                "incorrect."
            )
        else:
            summary = "The response does not satisfy the marking criteria."

        return AnswerEvaluationResult(
            awarded_marks=round(total_awarded, 2),
            max_marks=context.max_marks,
            confidence=confidence,
            reasoning=f"[Mock evaluation] {summary}",
            criteria=outcomes,
            strengths=strengths,
            gaps=gaps,
            contradictions=contradictions,
            flags=flags,
            raw={
                "mock": True,
                "seed": base_seed,
                "question": context.question_label,
                "criteria_evaluated": len(outcomes),
            },
            provider=self.name,
            model=self.model,
            prompt_version=prompt_version,
            is_mock=True,
        )

    async def health(self) -> dict:
        return {
            "provider": self.name,
            "model": self.model,
            "is_mock": True,
            "ok": True,
            "detail": "Mock provider is always available (no network calls are made).",
        }

    async def aclose(self) -> None:  # nothing to release
        return None
