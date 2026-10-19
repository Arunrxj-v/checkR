"""Google Gemini vision provider (generateContent / REST)."""

from __future__ import annotations

from typing import Any

from app.ai.base import AIProviderError
from app.ai.http_utils import (
    detect_mime,
    encode_b64,
    extract_json,
    make_client,
    map_criteria,
    post_with_retries,
    require_api_key,
)
from app.ai.schemas import RawEvaluation, RawOCR
from app.ai.types import (
    AnswerEvaluationResult,
    CriterionOutcome,
    EvaluationContext,
    OCRPageResult,
)
from app.core.config import settings

_DEFAULT_MODEL = "gemini-2.0-flash"
_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider:
    name = "gemini"
    is_mock = False

    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.ai_model or _DEFAULT_MODEL
        self._client = make_client(self.name)

    # ------------------------------------------------------------------ #
    async def _generate(self, system: str, user: str, images: list[bytes]) -> dict[str, Any]:
        key = require_api_key(self.name)
        parts: list[dict[str, Any]] = [{"text": user}]
        for img in images:
            parts.append(
                {"inline_data": {"mime_type": detect_mime(img), "data": encode_b64(img)}}
            )
        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }
        url = f"{_BASE}/{self.model}:generateContent?key={key}"
        data = await post_with_retries(
            self._client,
            url,
            json_body=body,
            headers={"Content-Type": "application/json"},
            provider_label="Gemini",
        )
        text = _text_of(data)
        if not text:
            raise AIProviderError(
                "Gemini response did not contain any text content.", retryable=True
            )
        return extract_json(text)

    # ------------------------------------------------------------------ #
    async def transcribe_page(
        self,
        image_bytes: bytes,
        *,
        page_number: int,
        prompt_version: str = "handwriting_v1",
    ) -> OCRPageResult:
        from app.prompts.registry import ocr_prompt

        module = ocr_prompt(prompt_version)
        user = module.build(page_number)
        raw = await self._generate(module.SYSTEM, user, [image_bytes])
        parsed = RawOCR.model_validate(raw)
        return OCRPageResult(
            text=parsed.text,
            confidence=parsed.confidence,
            regions=[r.model_dump() for r in parsed.regions],
            raw=raw,
            model=self.model,
            provider=self.name,
            prompt_version=prompt_version,
            is_mock=False,
        )

    # ------------------------------------------------------------------ #
    async def evaluate_answer(
        self, context: EvaluationContext, *, prompt_version: str
    ) -> AnswerEvaluationResult:
        from app.prompts.registry import build_evaluation_prompt

        system, user, version = build_evaluation_prompt(context)
        raw = await self._generate(system, user, context.images)
        parsed = RawEvaluation.model_validate(raw)
        criteria = map_criteria(
            [c.model_dump() for c in parsed.criteria], context.criteria, context.max_marks
        )
        return AnswerEvaluationResult(
            awarded_marks=parsed.awarded_marks,
            max_marks=context.max_marks,
            confidence=parsed.confidence,
            reasoning=parsed.reasoning,
            criteria=[
                CriterionOutcome(
                    name=c["name"],
                    max_marks=c["max_marks"],
                    awarded_marks=c["awarded_marks"],
                    satisfied=c["satisfied"],
                    comment=c["comment"],
                )
                for c in criteria
            ],
            strengths=parsed.strengths,
            gaps=parsed.gaps,
            contradictions=parsed.contradictions,
            flags=parsed.flags,
            raw=raw,
            provider=self.name,
            model=self.model,
            prompt_version=version,
            is_mock=False,
        )

    async def health(self) -> dict:
        ok = bool(settings.ai_api_key)
        return {
            "provider": self.name,
            "model": self.model,
            "is_mock": False,
            "ok": ok,
            "detail": "API key present." if ok else "AI_API_KEY is not set.",
        }

    async def aclose(self) -> None:
        await self._client.aclose()


def _text_of(data: dict[str, Any]) -> str:
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return ""
