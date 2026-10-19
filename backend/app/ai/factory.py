"""Provider factory — the only place that knows which provider is configured."""

from __future__ import annotations

from functools import lru_cache

from app.ai.base import AIProvider
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def build_provider(name: str | None = None) -> AIProvider:
    """Instantiate the configured AI provider.

    Imported lazily so an unused provider never pulls in its HTTP client.
    """
    provider = (name or settings.ai_provider or "mock").lower()

    if provider == "mock":
        from app.ai.mock import MockProvider

        return MockProvider()

    if provider == "gemini":
        from app.ai.gemini import GeminiProvider

        return GeminiProvider()

    if provider == "openai":
        from app.ai.openai import OpenAIProvider

        return OpenAIProvider()

    if provider == "anthropic":
        from app.ai.anthropic import AnthropicProvider

        return AnthropicProvider()

    if provider == "local":
        from app.ai.local import LocalVisionProvider

        return LocalVisionProvider()

    logger.warning("Unknown AI provider %r; falling back to mock.", provider)
    from app.ai.mock import MockProvider

    return MockProvider()


@lru_cache
def get_provider() -> AIProvider:
    """Process-wide provider singleton (holds an HTTP client)."""
    return build_provider()


async def shutdown_provider() -> None:
    try:
        provider = get_provider()
    except Exception:  # pragma: no cover - defensive
        return
    try:
        await provider.aclose()
    finally:
        get_provider.cache_clear()
