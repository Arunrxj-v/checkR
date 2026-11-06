"""Ollama provider — CheckR's production inference runtime.

Talks to a local Ollama server over its native API:

* ``GET  /api/tags`` — is Ollama reachable and is the configured model
  installed? (cached briefly so health checks do not hammer the server)
* ``POST /api/chat``  — vision and text inference. Vision requests carry the
  actual page image via Ollama's ``images`` field; nothing leaves the machine.

The same model (``OLLAMA_MODEL``, ``gemma3:4b``) serves both capabilities, but
OCR and evaluation keep separate prompts, separate validation and separate
provenance records.

Retry policy: one loop in :meth:`OllamaProvider._chat` covers the whole
request — transport failures, 5xx, empty/malformed model output and schema
validation failures are all retried up to ``OLLAMA_MAX_RETRIES`` times with
exponential backoff. Configuration problems (model not installed, wrong base
URL, capability disabled) are never retried.

If Ollama or the model is unavailable the provider raises
:class:`AIProviderError` with an actionable message — it never fabricates a
result and never falls back to another provider.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

import httpx
from pydantic import ValidationError

from app.ai.base import AIProviderError
from app.ai.http_utils import encode_b64, extract_json, map_criteria
from app.ai.schemas import RawEvaluation, RawOCR
from app.ai.types import (
    AnswerEvaluationResult,
    CriterionOutcome,
    EvaluationContext,
    OCRPageResult,
)
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

#: How long an availability result may be reused (seconds).
AVAILABILITY_TTL = 15.0
#: Timeout used for the cheap /api/tags probe (never the inference timeout).
PROBE_TIMEOUT = 5.0

#: Health states, shared with the Settings API and the UI. Ordered from
#: "cannot serve" to "verified working"; see :meth:`OllamaProvider.health`.
STATUS_UNAVAILABLE = "unavailable"        # Ollama cannot be reached
STATUS_ERROR = "error"                    # Ollama answered unexpectedly (HTTP/parse)
STATUS_MODEL_NOT_INSTALLED = "model_not_installed"
STATUS_CONNECTED = "connected"            # reachable + installed, inference unverified
STATUS_MODEL_LOADING = "model_loading"    # an inference request is in flight
STATUS_READY = "ready"                    # a real inference request has succeeded
STATUS_INFERENCE_ERROR = "inference_error"  # installed, but inference failed

#: How long a verified (or failed) inference result may be reused by the cheap
#: health endpoints before Settings runs a fresh model check.
INFERENCE_TTL = 60.0

UNAVAILABLE_MESSAGE = (
    "Ollama is unavailable. Start the local Ollama service to process answer sheets."
)


def display_name_for(model: str) -> str:
    """Human label for a model, e.g. ``gemma3:4b`` -> ``Gemma 3 4B · Local``."""
    base, _, tag = (model or "").partition(":")
    pretty = re.sub(r"(\d+)$", r" \1", base).strip()
    pretty = pretty[:1].upper() + pretty[1:] if pretty else base
    if tag and tag != "latest":
        return f"{pretty} {tag.upper()} · Local"
    return f"{pretty} · Local" if pretty else "Local model"


def _model_installed(names: list[str], model: str) -> bool:
    """Strict model presence check (no optimistic base-name matching)."""
    if model in names:
        return True
    if ":" not in model:
        return f"{model}:latest" in names
    return False


def _vision_capable(model_entry: dict) -> bool:
    """Whether a model entry from ``/api/tags`` accepts image input.

    Uses the explicit ``capabilities`` list (Ollama >= 0.5) and falls back to
    the GGUF ``families`` list (``clip`` is the vision projector family).
    ``False`` when neither is present: OCR availability is never assumed.
    """
    caps = model_entry.get("capabilities")
    if isinstance(caps, list) and caps:
        return "vision" in [str(c).lower() for c in caps]
    details = model_entry.get("details")
    families = details.get("families") if isinstance(details, dict) else None
    if isinstance(families, list) and families:
        return "clip" in [str(f).lower() for f in families]
    return False


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class OllamaProvider:
    """Local Ollama inference implementing the :class:`AIProvider` protocol."""

    name = "ollama"
    is_mock = False

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout = int(timeout or settings.ollama_request_timeout)
        self.max_retries = (
            int(max_retries) if max_retries is not None else settings.ollama_max_retries
        )
        self.display_name = display_name_for(self.model)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            headers={"User-Agent": "CheckR/ollama"},
            transport=transport,
        )
        self._availability_cache: tuple[float, dict[str, Any]] | None = None
        #: Last verified inference result (``status``/``inference_ok``/…) and
        #: when it was obtained; ``None`` until a real request has succeeded.
        self._inference_result: dict[str, Any] | None = None
        self._inference_at: float = 0.0
        #: True while a probe inference is in flight (-> ``model_loading``).
        self._probe_in_flight = False

    # ------------------------------------------------------------------ #
    # Connectivity / model availability (cheap: /api/tags + /api/ps)
    # ------------------------------------------------------------------ #
    async def availability(
        self, *, refresh: bool = False, probe_timeout: float = PROBE_TIMEOUT
    ) -> dict[str, Any]:
        """Check Ollama reachability, model installation and load state.

        TTL-cached so health endpoints do not hammer the server; ``refresh``
        forces a fresh probe (used by the processing preflight).
        """
        if not refresh and self._availability_cache is not None:
            cached_at, cached = self._availability_cache
            if time.monotonic() - cached_at < AVAILABILITY_TTL:
                return cached

        result = await self._probe(probe_timeout)
        self._availability_cache = (time.monotonic(), result)
        return result

    async def _probe(self, probe_timeout: float) -> dict[str, Any]:
        try:
            resp = await self._client.get(
                f"{self.base_url}/api/tags", timeout=probe_timeout
            )
        except httpx.TimeoutException:
            return self._status(
                STATUS_UNAVAILABLE,
                f"Ollama did not respond within {probe_timeout:g}s at {self.base_url}. "
                + UNAVAILABLE_MESSAGE,
            )
        except httpx.HTTPError as exc:
            return self._status(
                STATUS_UNAVAILABLE, f"{UNAVAILABLE_MESSAGE} ({type(exc).__name__})."
            )

        if resp.status_code >= 400:
            return self._status(
                STATUS_ERROR,
                f"Ollama returned HTTP {resp.status_code} at {self.base_url}. "
                + UNAVAILABLE_MESSAGE,
            )

        try:
            models = resp.json().get("models", [])
            names = [str(m.get("name", "")) for m in models]
        except (ValueError, AttributeError, TypeError):
            return self._status(
                STATUS_ERROR,
                f"Ollama returned an unreadable model list. {UNAVAILABLE_MESSAGE}",
            )

        if not _model_installed(names, self.model):
            return self._status(
                STATUS_MODEL_NOT_INSTALLED,
                f"{self.model} is not installed. Run: ollama pull {self.model}",
                model_installed=False,
            )

        entry = next(
            (m for m in models if _model_installed([str(m.get("name", ""))], self.model)),
            {},
        )
        vision = _vision_capable(entry if isinstance(entry, dict) else {})

        # Is the model already resident? Best-effort: a failing /api/ps must not
        # turn a healthy server into an error.
        loaded: bool | None = None
        try:
            ps = await self._client.get(f"{self.base_url}/api/ps", timeout=probe_timeout)
            if ps.status_code < 400:
                running = [str(m.get("name", "")) for m in ps.json().get("models", [])]
                loaded = _model_installed(running, self.model)
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            loaded = None

        detail = f"Ollama reachable at {self.base_url}; {self.model} installed."
        if loaded:
            detail += " Model is loaded in memory."
        return self._status(
            STATUS_CONNECTED,
            detail,
            model_installed=True,
            model_loaded=loaded,
            vision_capable=vision,
        )

    @staticmethod
    def _status(status: str, detail: str, **extra: Any) -> dict[str, Any]:
        connected = status == STATUS_CONNECTED
        return {
            "status": status,
            "ok": connected,
            "connected": connected,
            "available": connected,
            # Unknown until proven: an unreachable server tells us nothing
            # about what is installed.
            "model_installed": extra.get(
                "model_installed", False if status == STATUS_MODEL_NOT_INSTALLED else None
            ),
            "model_loaded": extra.get("model_loaded"),
            "vision_capable": extra.get("vision_capable"),
            "detail": detail,
            "checked_at": _now_iso(),
        }

    # ------------------------------------------------------------------ #
    # Real inference check: one tiny generation request
    # ------------------------------------------------------------------ #
    async def probe_inference(
        self, *, force: bool = False, timeout: float | None = None
    ) -> dict[str, Any]:
        """Send an actual inference request and report whether it succeeded.

        This is the only way the application claims ``ready``: no request, no
        success. Results are reused for ``OLLAMA_INFERENCE_TTL`` seconds so a
        page reload does not re-load the model; ``force`` bypasses the cache.
        """
        now = time.monotonic()
        if (
            not force
            and self._inference_result is not None
            and now - self._inference_at < settings.ollama_inference_ttl
        ):
            return dict(self._inference_result)

        if self._probe_in_flight:
            return {
                "status": STATUS_MODEL_LOADING,
                "ok": False,
                "connected": True,
                "inference_ok": None,
                "detail": (
                    f"{self.model} is loading into memory; the model check is "
                    "already running — retry in a moment."
                ),
            }

        self._probe_in_flight = True
        started = time.monotonic()
        try:
            request_timeout = timeout or settings.ollama_probe_timeout
            try:
                resp = await self._client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "user", "content": "Reply with the single word OK."}
                        ],
                        "stream": False,
                        "options": {"num_predict": 4},
                        "keep_alive": settings.ollama_keep_alive,
                    },
                    timeout=request_timeout,
                )
            except httpx.TimeoutException:
                result = self._inference_failure(
                    f"{self.model} did not complete inference within "
                    f"{request_timeout:g}s (it may still be loading). Increase "
                    "OLLAMA_PROBE_TIMEOUT or free system memory."
                )
            except httpx.HTTPError as exc:
                result = self._inference_failure(
                    f"Inference request failed ({type(exc).__name__}). "
                    + UNAVAILABLE_MESSAGE
                )
            else:
                if resp.status_code >= 400:
                    result = self._inference_failure(
                        f"Inference returned HTTP {resp.status_code}: "
                        f"{resp.text[:200]}"
                    )
                else:
                    try:
                        content = str(resp.json()["message"]["content"] or "")
                    except (ValueError, KeyError, TypeError, AttributeError):
                        content = ""
                    if content.strip():
                        elapsed_ms = int((time.monotonic() - started) * 1000)
                        result = {
                            "status": STATUS_READY,
                            "ok": True,
                            "connected": True,
                            "inference_ok": True,
                            "inference_ms": elapsed_ms,
                            "detail": (
                                f"Real inference verified: {self.model} responded "
                                f"in {elapsed_ms} ms."
                            ),
                        }
                    else:
                        result = self._inference_failure(
                            "The model returned an empty response to a real "
                            "inference request."
                        )

            result["inference_checked_at"] = _now_iso()
            self._inference_result = result
            self._inference_at = time.monotonic()
            return dict(result)
        finally:
            self._probe_in_flight = False

    def _inference_failure(self, detail: str) -> dict[str, Any]:
        return {
            "status": STATUS_INFERENCE_ERROR,
            "ok": False,
            "connected": True,
            "inference_ok": False,
            "detail": detail,
        }

    # ------------------------------------------------------------------ #
    # Combined status for the Settings/health endpoints
    # ------------------------------------------------------------------ #
    async def health(self) -> dict[str, Any]:
        """Real status of the local runtime — never inferred from existence.

        Cheap (cached tags probe); reports ``ready`` only when an actual
        inference request has succeeded recently, otherwise ``connected``
        (reachable but unverified) or one of the failure states.
        """
        state = await self.availability()
        payload: dict[str, Any] = {
            "provider": self.name,
            "model": self.model,
            "display_name": self.display_name,
            "is_mock": False,
            "base_url": self.base_url,
            "ocr_enabled": settings.ocr_enabled,
            "evaluation_enabled": settings.evaluation_enabled,
            "status": state["status"],
            "ok": bool(state["ok"]),
            "connected": bool(state.get("connected")),
            "available": bool(state.get("available")),
            "model_installed": state.get("model_installed"),
            "model_loaded": state.get("model_loaded"),
            "vision_capable": state.get("vision_capable"),
            # Tri-state: None until a real inference request has been made.
            "inference_ok": None,
            "inference_ms": None,
            "inference_checked_at": None,
            "checked_at": state.get("checked_at"),
            "detail": state["detail"],
        }
        if payload["status"] in (
            STATUS_UNAVAILABLE,
            STATUS_ERROR,
            STATUS_MODEL_NOT_INSTALLED,
        ):
            payload["ok"] = False
            payload["available"] = False
            return payload

        # Reachable and installed from here on.
        if self._probe_in_flight:
            payload.update(
                status=STATUS_MODEL_LOADING,
                ok=False,
                detail=f"{self.model} is loading into memory…",
            )
            return payload

        if (
            self._inference_result is not None
            and time.monotonic() - self._inference_at < settings.ollama_inference_ttl
        ):
            payload.update(self._inference_result)
            # A failed inference means the runtime cannot serve work right now,
            # even though the server itself is reachable.
            payload["available"] = bool(payload["ok"])
            return payload

        payload.update(
            status=STATUS_CONNECTED,
            ok=True,
            detail=(
                f"Ollama reachable and {self.model} installed. Inference has "
                "not been verified yet — the Settings screen runs a real model "
                "check."
            ),
        )
        if self._inference_result is not None:
            payload["inference_ok"] = self._inference_result.get("inference_ok")
            payload["inference_checked_at"] = self._inference_result.get(
                "inference_checked_at"
            )
        return payload

    async def require_available(self) -> None:
        """Raise an actionable error when inference cannot run right now."""
        state = await self.availability(refresh=True)
        if state["status"] in (STATUS_UNAVAILABLE, STATUS_ERROR):
            raise AIProviderError(state["detail"], retryable=True, kind="unavailable")
        if state["status"] == STATUS_MODEL_NOT_INSTALLED:
            raise AIProviderError(state["detail"], retryable=False, kind="model_missing")

    # ------------------------------------------------------------------ #
    # Transport — a single attempt; retries live in _chat
    # ------------------------------------------------------------------ #
    async def _post_once(self, body: dict[str, Any], *, timeout: int | None) -> dict[str, Any]:
        request_timeout = timeout or self.timeout
        try:
            resp = await self._client.post(
                f"{self.base_url}/api/chat",
                json=body,
                timeout=request_timeout,
                headers={"Content-Type": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise AIProviderError(
                f"Ollama request timed out after {request_timeout}s. "
                "Increase OLLAMA_REQUEST_TIMEOUT or use a smaller page image.",
                retryable=True,
                kind="timeout",
            ) from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(
                UNAVAILABLE_MESSAGE + f" ({type(exc).__name__}).",
                retryable=True,
                kind="unavailable",
            ) from exc

        if resp.status_code == 404 and "not found" in resp.text:
            # Model missing (404 {"error":"model 'x' not found"}) or a wrong
            # base URL (404 page not found). Neither is retryable.
            if "model" in resp.text:
                raise AIProviderError(
                    f"{self.model} is not installed. Run: ollama pull {self.model}",
                    retryable=False,
                    kind="model_missing",
                )
            raise AIProviderError(
                f"Ollama API endpoint not found at {self.base_url}. "
                "Check OLLAMA_BASE_URL.",
                retryable=False,
                kind="config",
            )
        if resp.status_code in (429, 500, 502, 503, 504):
            raise AIProviderError(
                f"Ollama returned HTTP {resp.status_code}. "
                "If this persists the machine may be low on memory; "
                "close other applications and retry.",
                retryable=True,
                kind="bad_response",
            )
        if resp.status_code >= 400:
            raise AIProviderError(
                f"Ollama rejected the request (HTTP {resp.status_code}): "
                f"{resp.text[:300]}",
                retryable=False,
                kind="bad_response",
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise AIProviderError(
                "Ollama returned a non-JSON response.",
                retryable=True,
                kind="bad_response",
            ) from exc

        # Ollama signals some failures with HTTP 200 + an "error" field.
        if isinstance(data, dict) and data.get("error"):
            raise AIProviderError(
                f"Ollama error: {str(data['error'])[:300]}",
                retryable=False,
                kind="bad_response",
            )
        return data

    # ------------------------------------------------------------------ #
    # One inference request: transport + parse + validate, with retries
    # ------------------------------------------------------------------ #
    async def _chat(
        self,
        system: str,
        user: str,
        images: list[bytes],
        *,
        parse: Callable[[dict[str, Any]], T] | None = None,
        temperature: float = 0.1,
        timeout: int | None = None,
    ) -> Any:
        """Run one JSON-shaped inference request and return its parsed result.

        Retries (``OLLAMA_MAX_RETRIES``) cover transport failures *and* model
        output that cannot be parsed or validated — never configuration errors.
        """
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if images:
            messages[1]["images"] = [encode_b64(img) for img in images]

        body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "format": "json",  # structured output: the model must answer JSON
            "keep_alive": settings.ollama_keep_alive,
            "options": {"temperature": temperature},
            "messages": messages,
        }

        attempts = max(1, self.max_retries + 1)
        last_error: AIProviderError | None = None
        for attempt in range(attempts):
            try:
                data = await self._post_once(body, timeout=timeout)
                try:
                    text = data["message"]["content"] or ""
                except (KeyError, TypeError) as exc:
                    raise AIProviderError(
                        "Ollama returned no message content.",
                        retryable=True,
                        kind="bad_response",
                    ) from exc
                if not text.strip():
                    raise AIProviderError(
                        "Ollama returned an empty response.",
                        retryable=True,
                        kind="bad_response",
                    )
                raw = extract_json(text)
                if parse is None:
                    return raw
                try:
                    return parse(raw)
                except ValidationError as exc:
                    first = exc.errors()[0] if exc.errors() else {}
                    raise AIProviderError(
                        "Model response failed schema validation: "
                        f"{first.get('loc', ['?'])} {first.get('msg', '')}",
                        retryable=True,
                        kind="bad_response",
                    ) from exc
            except AIProviderError as exc:
                if not exc.retryable:
                    raise
                last_error = exc
                logger.debug(
                    "Ollama request attempt %s/%s failed (%s): %s",
                    attempt + 1,
                    attempts,
                    exc.kind or "retryable",
                    exc,
                )
                if attempt < attempts - 1:
                    await asyncio.sleep(1.5 * (2**attempt))

        raise last_error or AIProviderError(
            "Ollama request failed.", retryable=True, kind="bad_response"
        )

    # ------------------------------------------------------------------ #
    # Capability 1: handwriting recognition (vision)
    # ------------------------------------------------------------------ #
    async def transcribe_page(
        self,
        image_bytes: bytes,
        *,
        page_number: int,
        prompt_version: str = "handwriting_v2",
        previous_context: str | None = None,
    ) -> OCRPageResult:
        from app.prompts.registry import ocr_prompt

        if not image_bytes:
            raise AIProviderError(
                "Empty page image supplied to OCR.", retryable=False, kind="config"
            )
        if not settings.ocr_enabled:
            raise AIProviderError(
                "Handwriting recognition is disabled (OCR_ENABLED=false).",
                retryable=False,
                kind="config",
            )

        module = ocr_prompt(prompt_version)
        user = module.build(page_number, previous_context=previous_context)
        parsed: RawOCR = await self._chat(
            module.SYSTEM, user, [image_bytes], parse=RawOCR.model_validate
        )

        return OCRPageResult(
            text=parsed.text,
            confidence=parsed.confidence,
            regions=[r.model_dump() for r in parsed.regions],
            raw=parsed.model_dump(),
            model=self.model,
            provider=self.name,
            prompt_version=prompt_version,
            is_mock=False,
            detected_answers=[a.model_dump() for a in parsed.detected_answers],
            diagrams=[d.model_dump() for d in parsed.diagrams],
            unreadable_regions=[u.model_dump() for u in parsed.unreadable_regions],
            manual_review_required=parsed.manual_review_required,
        )

    # ------------------------------------------------------------------ #
    # Capability 2: answer evaluation
    # ------------------------------------------------------------------ #
    async def evaluate_answer(
        self, context: EvaluationContext, *, prompt_version: str
    ) -> AnswerEvaluationResult:
        from app.prompts.registry import build_evaluation_prompt

        if not settings.evaluation_enabled:
            raise AIProviderError(
                "AI evaluation is disabled (EVALUATION_ENABLED=false).",
                retryable=False,
                kind="config",
            )

        system, user, version = build_evaluation_prompt(context)
        parsed: RawEvaluation = await self._chat(
            system, user, context.images, parse=RawEvaluation.model_validate
        )
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
            raw=parsed.model_dump(),
            provider=self.name,
            model=self.model,
            prompt_version=version,
            is_mock=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
