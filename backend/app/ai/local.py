"""Local / self-hosted vision provider.

Targets any OpenAI-compatible server (Ollama, vLLM, LM Studio, llama.cpp).
No API key is required; the endpoint comes from ``AI_BASE_URL``.
"""

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
)
from app.ai.schemas import RawEvaluation, RawOCR
from app.ai.types import (
    AnswerEvaluationResult,
    CriterionOutcome,
    EvaluationContext,
    OCRPageResult,
)
from app.core.config import settings

_DEFAULT_MODEL = "llava"
_DEFAULT_BASE = "http://localhost:11434/v1"


class LocalVisionProvider:
    name = "local"
    is_mock = False

    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.ai_model or _DEFAULT_MODEL
        self._base = (settings.ai_base_url or _DEFAULT_BASE).rstrip("/")
        self._client = make_client(self.name)

    async def _chat(self, system: str, user: str, images: list[bytes]) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": user}]
        for img in images:
            mime = detect_mime(img)
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{encode_b64(img)}"},
                }
            )
        body = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if settings.ai_api_key:
            headers["Authorization"] = f"Bearer {settings.ai_api_key}"

        data = await post_with_retries(
            self._client,
            f"{self._base}/chat/completions",
            json_body=body,
            headers=headers,
            provider_label="Local vision server",
        )
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                "Local vision server returned no message content.", retryable=True
            ) from exc
        return extract_json(text)

    async def transcribe_page(
        self,
        image_bytes: bytes,
        *,
        page_number: int,
        prompt_version: str = "handwriting_v1",
    ) -> OCRPageResult:
        from app.prompts.registry import ocr_prompt

        module = ocr_prompt(prompt_version)
        raw = await self._chat(module.SYSTEM, module.build(page_number), [image_bytes])
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

    async def evaluate_answer(
        self, context: EvaluationContext, *, prompt_version: str
    ) -> AnswerEvaluationResult:
        from app.prompts.registry import build_evaluation_prompt

        system, user, version = build_evaluation_prompt(context)
        raw = await self._chat(system, user, context.images)
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
        return {
            "provider": self.name,
            "model": self.model,
            "is_mock": False,
            "ok": bool(settings.ai_base_url),
            "detail": (
                f"Endpoint configured: {settings.ai_base_url}"
                if settings.ai_base_url
                else "AI_BASE_URL is not set."
            ),
        }

    async def aclose(self) -> None:
        await self._client.aclose()
