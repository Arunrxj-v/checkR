"""Provider factory — the only place that knows which provider is configured.

CheckR's production workflow runs on the local Ollama provider. The ``mock``
provider exists only for the test suite and the development seed: it must be
requested *explicitly* (``AI_PROVIDER=mock``). An unknown provider name is a
configuration error — it never degrades into mock results.
"""

from __future__ import annotations

from functools import lru_cache

from app.ai.base import AIProvider, AIProviderError
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def build_provider(name: str | None = None) -> AIProvider:
    """Instantiate the configured AI provider.

    Imported lazily so an unused provider never pulls in its HTTP client.
    """
    provider = (name or settings.ai_provider or "ollama").lower()

    if provider == "ollama":
        from app.ai.ollama import OllamaProvider

        return OllamaProvider()

    if provider == "mock":
        # Explicit opt-in only: tests and the deterministic development seed.
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

    # Never fall back to mock: fabricated results are worse than a clear error.
    raise AIProviderError(
        f"Unknown AI provider {provider!r}. Set AI_PROVIDER to one of: "
        "ollama, local, gemini, openai, anthropic (mock is for tests only).",
        retryable=False,
        kind="config",
    )


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
