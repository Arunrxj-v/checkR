"""Ollama provider — CheckR's dual-model local inference runtime.

Talks to a local Ollama server over its native API:

* ``GET  /api/tags`` — is Ollama reachable and are both configured models
  installed? (cached briefly so health checks do not hammer the server)
* ``GET  /api/ps``   — which models are currently resident in memory.
* ``POST /api/chat`` — vision and text inference. Vision requests carry the
  actual page image via Ollama's ``images`` field; nothing leaves the machine.
* ``POST /api/generate`` (``keep_alive: 0``) — unload a model at a stage
  boundary so only one model is ever resident on an 8 GB machine.

Two models, used sequentially:

* ``OLLAMA_OCR_MODEL`` (Qwen3-VL) transcribes page images;
* ``OLLAMA_EVALUATION_MODEL`` (Qwen2.5) grades transcribed answers **as text**
  — it has no vision capability, so page images are never attached to it.

Memory discipline (8 GB M1): the Settings probe runs the two checks strictly
one after the other and unloads each model immediately (``keep_alive: 0``);
processing stages unload their model when the stage ends. A per-process lock
serialises every request so a health probe never races a pipeline request.

Retry policy: one loop in :meth:`OllamaProvider._chat` covers the whole
request — transport failures, 5xx, empty/malformed model output and schema
validation failures are all retried up to ``OLLAMA_MAX_RETRIES`` times with
exponential backoff. Configuration problems (model not installed, wrong base
URL, capability disabled) are never retried.

If Ollama or a model is unavailable the provider raises
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

#: Roles in the order they are probed (OCR first, then evaluation) so the two
#: models are never loaded at the same time.
MODEL_ROLES: tuple[str, ...] = ("ocr", "evaluation")

PROVIDER_DISPLAY_NAME = "Ollama Local AI"

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


def model_label(model: str) -> str:
    """Compact model label for the Settings screen.

    ``qwen3-vl:2b-instruct-q4_K_M`` -> ``Qwen3-VL 2B``,
    ``qwen2.5:1.5b`` -> ``Qwen2.5 1.5B``, ``gemma3:4b`` -> ``Gemma3 4B``.
    The size comes from the tag so the label follows the installed model
    instead of being hardcoded anywhere.
    """
    base, _, tag = (model or "").partition(":")
    if not base:
        return "Local model"
    parts: list[str] = []
    for segment in base.split("-"):
        segment = segment.strip()
        if not segment:
            continue
        segment = segment[0].upper() + segment[1:]
        # Short all-letter segments (``vl``, ``instruct``) read better uppercase.
        if segment.isalpha() and len(segment) <= 4:
            segment = segment.upper()
        parts.append(segment)
    pretty = "-".join(parts)
    size = re.match(r"(\d+(?:\.\d+)?)[bB]", tag or "")
    if size:
        return f"{pretty} {size.group(1).upper()}B"
    return pretty


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
    #: Human label for the provider itself (Settings screen).
    provider_display_name = PROVIDER_DISPLAY_NAME

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        ocr_model: str | None = None,
        evaluation_model: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        # Legacy single-model constructor: an explicit ``model`` sets both roles.
        default_ocr = model or settings.ocr_model
        default_eval = model or settings.evaluation_model
        self.ocr_model = ocr_model or default_ocr
        self.evaluation_model = evaluation_model or default_eval
        #: Legacy single-model attribute — points at the evaluation model so
        #: older call sites (provenance ``model_version``) keep working.
        self.model = self.evaluation_model
        self.timeout = int(timeout or settings.ollama_request_timeout)
        self.max_retries = (
            int(max_retries) if max_retries is not None else settings.ollama_max_retries
        )
        self.display_name = display_name_for(self.evaluation_model)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            headers={"User-Agent": "CheckR/ollama"},
            transport=transport,
        )
        self._availability_cache: tuple[float, dict[str, Any]] | None = None
        #: Last verified inference result (aggregate + per model) and when it
        #: was obtained; ``None`` until a real request has succeeded.
        self._inference_result: dict[str, Any] | None = None
        self._inference_at: float = 0.0
        #: True while a probe inference is in flight (-> ``model_loading``).
        self._probe_in_flight = False
        #: Serialises every request inside this process so a Settings probe
        #: never overlaps a pipeline request (or an unload) here.
        self._infer_lock = asyncio.Lock()
        #: Roles loaded with a keep-alive since the last stage-boundary unload.
        self._dirty: set[str] = set()

    # ------------------------------------------------------------------ #
    # Connectivity / model availability (cheap: /api/tags + /api/ps)
    # ------------------------------------------------------------------ #
    async def availability(
        self, *, refresh: bool = False, probe_timeout: float = PROBE_TIMEOUT
    ) -> dict[str, Any]:
        """Check Ollama reachability and that BOTH models are installed.

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

    def _role_model(self, role: str) -> str:
        return self.ocr_model if role == "ocr" else self.evaluation_model

    def _role_label(self, role: str) -> str:
        return "OCR" if role == "ocr" else "Evaluation"

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
                models=self._unavailable_models(STATUS_UNAVAILABLE),
            )
        except httpx.HTTPError as exc:
            return self._status(
                STATUS_UNAVAILABLE,
                f"{UNAVAILABLE_MESSAGE} ({type(exc).__name__}).",
                models=self._unavailable_models(STATUS_UNAVAILABLE),
            )

        if resp.status_code >= 400:
            return self._status(
                STATUS_ERROR,
                f"Ollama returned HTTP {resp.status_code} at {self.base_url}. "
                + UNAVAILABLE_MESSAGE,
                models=self._unavailable_models(STATUS_ERROR),
            )

        try:
            models = resp.json().get("models", [])
            names = [str(m.get("name", "")) for m in models]
        except (ValueError, AttributeError, TypeError):
            return self._status(
                STATUS_ERROR,
                f"Ollama returned an unreadable model list. {UNAVAILABLE_MESSAGE}",
                models=self._unavailable_models(STATUS_ERROR),
            )

        # --- Per-model installation check (both roles must be present) ----- #
        missing = [
            m
            for m in dict.fromkeys((self.ocr_model, self.evaluation_model))
            if not _model_installed(names, m)
        ]
        role_entries: dict[str, dict[str, Any]] = {}
        for role in MODEL_ROLES:
            name = self._role_model(role)
            entry = next(
                (m for m in models if _model_installed([str(m.get("name", ""))], name)),
                {},
            )
            installed = name not in missing
            role_entries[role] = {
                "name": name,
                "label": model_label(name),
                "role": role,
                "installed": installed,
                "loaded": None,
                "vision_capable": _vision_capable(entry if isinstance(entry, dict) else {}),
                "status": STATUS_MODEL_NOT_INSTALLED if not installed else STATUS_CONNECTED,
                "detail": (
                    f"{name} is not installed. Run: ollama pull {name}"
                    if not installed
                    else f"{name} installed."
                ),
            }

        if missing:
            detail = "; ".join(f"{m} is not installed. Run: ollama pull {m}" for m in missing)
            return self._status(
                STATUS_MODEL_NOT_INSTALLED,
                detail,
                model_installed=False,
                models=role_entries,
            )

        # Is a model already resident? Best-effort: a failing /api/ps must not
        # turn a healthy server into an error.
        try:
            ps = await self._client.get(f"{self.base_url}/api/ps", timeout=probe_timeout)
            running: list[str] = []
            if ps.status_code < 400:
                running = [str(m.get("name", "")) for m in ps.json().get("models", [])]
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            running = []
        for role in MODEL_ROLES:
            name = self._role_model(role)
            loaded = _model_installed(running, name)
            role_entries[role]["loaded"] = loaded
            role_entries[role]["detail"] += (
                " Loaded in memory." if loaded else " Not currently loaded."
            )

        detail = (
            f"Ollama reachable at {self.base_url}; "
            f"{self.ocr_model} (OCR) and {self.evaluation_model} (evaluation) installed."
        )
        if any(e["loaded"] for e in role_entries.values()):
            detail += " A model is loaded in memory."
        return self._status(
            STATUS_CONNECTED,
            detail,
            model_installed=True,
            model_loaded=role_entries["evaluation"]["loaded"],
            vision_capable=role_entries["ocr"]["vision_capable"],
            models=role_entries,
        )

    def _unavailable_models(self, status: str) -> dict[str, dict[str, Any]]:
        return {
            role: {
                "name": self._role_model(role),
                "label": model_label(self._role_model(role)),
                "role": role,
                "installed": None,
                "loaded": None,
                "vision_capable": None,
                "status": status,
                "detail": UNAVAILABLE_MESSAGE,
            }
            for role in MODEL_ROLES
        }

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
            "models": extra.get("models", {}),
            "detail": detail,
            "checked_at": _now_iso(),
        }

    # ------------------------------------------------------------------ #
    # Real inference check: one tiny generation request per model, in order
    # ------------------------------------------------------------------ #
    async def probe_inference(
        self, *, force: bool = False, timeout: float | None = None
    ) -> dict[str, Any]:
        """Send an actual inference request per model and report the results.

        This is the only way the application claims ``ready``: no request, no
        success. The two models are probed strictly sequentially and each is
        unloaded immediately (``keep_alive: 0``) before the next one starts,
        so both are never resident at once. Results are reused for
        ``OLLAMA_INFERENCE_TTL`` seconds; ``force`` bypasses the cache.
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
                    "A model check is already running — the model is loading into "
                    "memory; retry in a moment."
                ),
            }

        self._probe_in_flight = True
        started = time.monotonic()
        try:
            per_role: dict[str, dict[str, Any]] = {}
            for role in MODEL_ROLES:
                # Sequential by construction: the previous model is unloaded
                # before the next probe request is sent.
                per_role[role] = await self._probe_model(
                    role, self._role_model(role), timeout
                )
                await self._ensure_unloaded(self._role_model(role))
            elapsed_ms = int((time.monotonic() - started) * 1000)
            result = self._combine_probes(per_role, elapsed_ms)
            result["inference_checked_at"] = _now_iso()
            self._inference_result = result
            self._inference_at = time.monotonic()
            return dict(result)
        finally:
            self._probe_in_flight = False

    async def _probe_model(
        self, role: str, model: str, timeout: float | None
    ) -> dict[str, Any]:
        request_timeout = timeout or settings.ollama_probe_timeout
        started = time.monotonic()
        try:
            resp = await self._client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "user", "content": "Reply with the single word OK."}
                    ],
                    "stream": False,
                    "options": {"num_predict": 4, "num_ctx": settings.ollama_num_ctx},
                    # Unload as soon as the check finishes: the probe must not
                    # leave a model resident on an 8 GB machine.
                    "keep_alive": 0,
                },
                timeout=request_timeout,
            )
        except httpx.TimeoutException:
            return self._inference_failure(
                f"{model} did not complete inference within "
                f"{request_timeout:g}s (it may still be loading). Increase "
                "OLLAMA_PROBE_TIMEOUT or free system memory."
            )
        except httpx.HTTPError as exc:
            return self._inference_failure(
                f"Inference request failed ({type(exc).__name__}). " + UNAVAILABLE_MESSAGE
            )

        if resp.status_code >= 400:
            return self._inference_failure(
                f"Inference returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            content = str(resp.json()["message"]["content"] or "")
        except (ValueError, KeyError, TypeError, AttributeError):
            content = ""
        if not content.strip():
            return self._inference_failure(
                f"{model} returned an empty response to a real inference request."
            )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "status": STATUS_READY,
            "ok": True,
            "inference_ok": True,
            "inference_ms": elapsed_ms,
            "detail": (
                f"Real inference verified: {model} ({self._role_label(role)}) "
                f"responded in {elapsed_ms} ms."
            ),
        }

    def _combine_probes(
        self, per_role: dict[str, dict[str, Any]], elapsed_ms: int
    ) -> dict[str, Any]:
        failed = [r for r in MODEL_ROLES if not per_role.get(r, {}).get("ok")]
        if failed:
            first = per_role[failed[0]]
            status, ok, inference_ok = STATUS_INFERENCE_ERROR, False, False
            detail = first.get("detail", "Inference failed.")
        else:
            status, ok, inference_ok = STATUS_READY, True, True
            parts = ", ".join(
                f"{self._role_model(r)} ({self._role_label(r)})" for r in MODEL_ROLES
            )
            detail = f"Real inference verified for {parts} in {elapsed_ms} ms."
        return {
            "status": status,
            "ok": ok,
            "connected": True,
            "available": ok,
            "inference_ok": inference_ok,
            "inference_ms": elapsed_ms,
            "detail": detail,
            "models": {
                role: dict(result, role=role, name=self._role_model(role))
                for role, result in per_role.items()
            },
        }

    def _inference_failure(self, detail: str) -> dict[str, Any]:
        return {
            "status": STATUS_INFERENCE_ERROR,
            "ok": False,
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
        (reachable but unverified) or one of the failure states. The payload
        carries per-model (``models.ocr`` / ``models.evaluation``) status so
        the Settings screen can show each model's real state.
        """
        state = await self.availability()
        payload: dict[str, Any] = {
            "provider": self.name,
            "provider_display_name": PROVIDER_DISPLAY_NAME,
            "model": self.evaluation_model,
            "display_name": display_name_for(self.evaluation_model),
            "ocr_model": self.ocr_model,
            "evaluation_model": self.evaluation_model,
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
            "models": {
                role: dict(entry) for role, entry in (state.get("models") or {}).items()
            },
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
                detail="A model check is in progress — the model is loading into memory…",
            )
            for entry in payload["models"].values():
                entry["status"] = STATUS_MODEL_LOADING
                entry["detail"] = "Model check in progress…"
            return payload

        if (
            self._inference_result is not None
            and time.monotonic() - self._inference_at < settings.ollama_inference_ttl
        ):
            inference = self._inference_result
            payload.update(
                {
                    k: v
                    for k, v in inference.items()
                    if k not in ("models", "available")
                }
            )
            # A failed inference means the runtime cannot serve work right now,
            # even though the server itself is reachable.
            payload["available"] = bool(payload["ok"])
            for role, entry in (inference.get("models") or {}).items():
                if role in payload["models"]:
                    payload["models"][role].update(entry)
            return payload

        payload.update(
            status=STATUS_CONNECTED,
            ok=True,
            detail=(
                f"Ollama reachable; {self.ocr_model} (OCR) and "
                f"{self.evaluation_model} (evaluation) installed. Inference has "
                "not been verified yet — the Settings screen runs a real model "
                "check."
            ),
        )
        return payload

    async def require_available(self) -> None:
        """Raise an actionable error when inference cannot run right now."""
        state = await self.availability(refresh=True)
        if state["status"] in (STATUS_UNAVAILABLE, STATUS_ERROR):
            raise AIProviderError(state["detail"], retryable=True, kind="unavailable")
        if state["status"] == STATUS_MODEL_NOT_INSTALLED:
            raise AIProviderError(state["detail"], retryable=False, kind="model_missing")

    async def accepts_evaluation_images(self) -> bool:
        """Whether the configured evaluation model can take page images.

        Driven by Ollama's reported capabilities, never by assumption: the
        configured Qwen2.5 evaluator is text-only, so images must not be sent
        (Ollama would reject them).
        """
        state = await self.availability()
        entry = (state.get("models") or {}).get("evaluation") or {}
        return bool(entry.get("vision_capable"))

    # ------------------------------------------------------------------ #
    # Stage-boundary unload (memory discipline on 8 GB machines)
    # ------------------------------------------------------------------ #
    async def unload_models(
        self, *, roles: tuple[str, ...] = MODEL_ROLES
    ) -> list[str]:
        """Unload resident models at a stage boundary.

        Only models this provider loaded with a keep-alive since the last
        unload are touched, so an idle stage never triggers a pointless load.
        Best-effort: a failing unload is logged, never raised — unloading must
        not fail a completed stage. Returns the models actually unloaded.
        """
        unloaded: list[str] = []
        for role in roles:
            if role not in self._dirty:
                continue
            model = self._role_model(role)
            if await self._ensure_unloaded(model):
                unloaded.append(model)
            self._dirty.discard(role)
        if unloaded:
            logger.info("Unloaded model(s) at stage boundary: %s", ", ".join(unloaded))
        return unloaded

    async def _ensure_unloaded(self, model: str) -> bool:
        """Unload ``model`` if it is resident. Returns True when unloaded."""
        loaded = await self._model_resident(model)
        if not loaded:
            return False
        try:
            async with self._infer_lock:
                resp = await self._client.post(
                    f"{self.base_url}/api/generate",
                    json={"model": model, "keep_alive": 0},
                    timeout=min(self.timeout, 60),
                )
            if resp.status_code >= 400:
                logger.warning(
                    "Unload request for %s failed (HTTP %s): %s",
                    model,
                    resp.status_code,
                    resp.text[:200],
                )
                return False
            return True
        except httpx.HTTPError as exc:
            logger.warning("Could not unload %s: %s", model, exc)
            return False

    async def _model_resident(self, model: str) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/api/ps", timeout=PROBE_TIMEOUT)
            if resp.status_code >= 400:
                return False
            running = [str(m.get("name", "")) for m in resp.json().get("models", [])]
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            return False
        return _model_installed(running, model)

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

        error_text = resp.text.lower()
        if "out of memory" in error_text or "not enough memory" in error_text:
            raise AIProviderError(
                f"Ollama ran out of memory running {body.get('model')}. Close "
                "other applications, or lower OLLAMA_NUM_CTX, then retry.",
                retryable=True,
                kind="oom",
            )

        if resp.status_code == 404 and "not found" in resp.text:
            # Model missing (404 {"error":"model 'x' not found"}) or a wrong
            # base URL (404 page not found). Neither is retryable.
            if "model" in resp.text:
                raise AIProviderError(
                    f"{body.get('model')} is not installed. "
                    f"Run: ollama pull {body.get('model')}",
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
        model: str | None = None,
        role: str = "evaluation",
        parse: Callable[[dict[str, Any]], T] | None = None,
        temperature: float = 0.1,
        timeout: int | None = None,
    ) -> Any:
        """Run one JSON-shaped inference request and return its parsed result.

        Retries (``OLLAMA_MAX_RETRIES``) cover transport failures *and* model
        output that cannot be parsed or validated — never configuration errors.
        """
        target = model or self.evaluation_model
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if images:
            messages[1]["images"] = [encode_b64(img) for img in images]

        body: dict[str, Any] = {
            "model": target,
            "stream": False,
            "format": "json",  # structured output: the model must answer JSON
            "keep_alive": settings.ollama_keep_alive,
            "options": {
                "temperature": temperature,
                "num_ctx": settings.ollama_num_ctx,
            },
            "messages": messages,
        }

        attempts = max(1, self.max_retries + 1)
        last_error: AIProviderError | None = None
        for attempt in range(attempts):
            try:
                async with self._infer_lock:
                    data = await self._post_once(body, timeout=timeout)
                # Real work keeps the model resident between pages; remember
                # the role so the stage boundary can unload it later.
                self._dirty.add(role)
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
    # Capability 1: handwriting recognition (vision — OCR model)
    # ------------------------------------------------------------------ #
    async def transcribe_page(
        self,
        image_bytes: bytes,
        *,
        page_number: int,
        prompt_version: str = "handwriting_v3",
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
        started = time.monotonic()
        parsed: RawOCR = await self._chat(
            module.SYSTEM,
            user,
            [image_bytes],
            model=self.ocr_model,
            role="ocr",
            parse=RawOCR.model_validate,
        )
        duration_ms = int((time.monotonic() - started) * 1000)

        return OCRPageResult(
            text=parsed.text,
            confidence=parsed.confidence,
            regions=[r.model_dump() for r in parsed.regions],
            raw=parsed.model_dump(),
            model=self.ocr_model,
            provider=self.name,
            prompt_version=prompt_version,
            is_mock=False,
            detected_answers=[a.model_dump() for a in parsed.detected_answers],
            diagrams=[d.model_dump() for d in parsed.diagrams],
            unreadable_regions=[u.model_dump() for u in parsed.unreadable_regions],
            manual_review_required=parsed.manual_review_required,
            duration_ms=duration_ms,
        )

    # ------------------------------------------------------------------ #
    # Capability 2: answer evaluation (text-only — evaluation model)
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

        # The evaluation model is text-only (Qwen2.5 has no vision): page
        # images are never attached. Grading works from the OCR transcription.
        images: list[bytes] = []
        if context.images and await self.accepts_evaluation_images():
            images = list(context.images)

        system, user, version = build_evaluation_prompt(context)
        started = time.monotonic()
        parsed: RawEvaluation = await self._chat(
            system,
            user,
            images,
            model=self.evaluation_model,
            role="evaluation",
            parse=RawEvaluation.model_validate,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
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
                    evidence=c.get("evidence", []),
                    missing_elements=c.get("missing_elements", []),
                    needs_human_review=bool(c.get("needs_human_review", False)),
                )
                for c in criteria
            ],
            strengths=parsed.strengths,
            gaps=parsed.gaps,
            contradictions=parsed.contradictions,
            flags=parsed.flags,
            needs_human_review=parsed.needs_human_review,
            raw=parsed.model_dump(),
            provider=self.name,
            model=self.evaluation_model,
            prompt_version=version,
            is_mock=False,
            duration_ms=duration_ms,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
