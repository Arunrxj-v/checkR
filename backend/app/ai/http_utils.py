"""Shared helpers for HTTP-based AI providers."""

from __future__ import annotations

import asyncio
import base64
import json
import re
from typing import Any

import httpx

from app.ai.base import AIProviderError
from app.core.config import settings

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def encode_b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def detect_mime(data: bytes) -> str:
    """Best-effort MIME sniffing for the common image formats we accept."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model response.

    Models sometimes wrap JSON in markdown fences or add a leading sentence.
    We never "repair" broken JSON into fabricated values — we raise instead.
    """
    if not text or not text.strip():
        raise AIProviderError("Model returned an empty response.", retryable=True)

    candidate = text.strip()

    fence = _JSON_FENCE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AIProviderError(
            f"Model response was not valid JSON: {exc.msg}", retryable=True
        ) from exc

    if not isinstance(parsed, dict):
        raise AIProviderError("Model response JSON was not an object.", retryable=True)
    return parsed


def make_client(provider_label: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.ai_timeout_seconds),
        headers={"User-Agent": f"CheckR/{provider_label}"},
    )


async def post_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    json_body: dict,
    headers: dict[str, str],
    provider_label: str,
) -> dict[str, Any]:
    """POST with bounded exponential backoff on retryable failures."""
    attempts = max(1, settings.ai_max_retries + 1)
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            resp = await client.post(url, json=json_body, headers=headers)
        except httpx.TimeoutException as exc:
            last_error = AIProviderError(
                f"{provider_label} request timed out.", retryable=True
            )
            last_error.__cause__ = exc
        except httpx.HTTPError as exc:
            last_error = AIProviderError(
                f"{provider_label} network error: {exc}", retryable=True
            )
            last_error.__cause__ = exc
        else:
            if resp.status_code in (429, 500, 502, 503, 504):
                last_error = AIProviderError(
                    f"{provider_label} returned HTTP {resp.status_code}.",
                    retryable=True,
                )
            elif resp.status_code >= 400:
                # 4xx other than 429 => configuration/auth problem, not retryable.
                raise AIProviderError(
                    f"{provider_label} rejected the request (HTTP {resp.status_code}): "
                    f"{resp.text[:300]}",
                    retryable=False,
                )
            else:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise AIProviderError(
                        f"{provider_label} returned a non-JSON HTTP body.",
                        retryable=True,
                    ) from exc

        if attempt < attempts - 1:
            await asyncio.sleep(1.5 * (2**attempt))

    raise last_error or AIProviderError(f"{provider_label} request failed.")


def require_api_key(provider_label: str) -> str:
    key = (settings.ai_api_key or "").strip()
    if not key:
        raise AIProviderError(
            f"AI_PROVIDER={provider_label} requires AI_API_KEY to be set.",
            retryable=False,
        )
    return key


# --------------------------------------------------------------------------- #
# Shared evaluation mapping
# --------------------------------------------------------------------------- #
def map_criteria(
    raw_criteria: list[dict],
    scheme: list[dict],
    max_marks: float,
) -> list[dict]:
    """Align model-returned criteria with the question's actual scheme.

    The scheme is authoritative: unknown criteria are dropped, missing ones are
    filled with zero. Names are matched case-insensitively by substring so minor
    rewording by the model does not lose marks.
    """
    by_name: dict[str, dict] = {}
    unused = list(range(len(scheme)))

    for raw in raw_criteria:
        name = str(raw.get("name", "")).strip()
        matched_idx = None
        lowered = name.lower()
        for idx in unused:
            scheme_name = str(scheme[idx].get("name", "")).lower()
            if scheme_name == lowered or scheme_name in lowered or lowered in scheme_name:
                matched_idx = idx
                break
        if matched_idx is None:
            continue
        unused.remove(matched_idx)
        by_name[str(matched_idx)] = raw

    result: list[dict] = []
    for idx, crit in enumerate(scheme):
        scheme_max = float(crit.get("max_marks", 0) or 0)
        raw = by_name.get(str(idx), {})
        awarded = float(raw.get("awarded_marks", 0) or 0)
        awarded = max(0.0, min(scheme_max, awarded))
        result.append(
            {
                "name": crit.get("name"),
                "max_marks": scheme_max,
                "awarded_marks": awarded,
                "satisfied": bool(raw.get("satisfied", awarded > 0)),
                "comment": raw.get("comment") or None,
            }
        )

    # If the scheme was empty, synthesise a single criterion from the raw list.
    if not scheme:
        for raw in raw_criteria:
            awarded = float(raw.get("awarded_marks", 0) or 0)
            result.append(
                {
                    "name": raw.get("name") or "Overall answer",
                    "max_marks": float(raw.get("max_marks") or max_marks or 0),
                    "awarded_marks": awarded,
                    "satisfied": bool(raw.get("satisfied", awarded > 0)),
                    "comment": raw.get("comment"),
                }
            )
    return result
