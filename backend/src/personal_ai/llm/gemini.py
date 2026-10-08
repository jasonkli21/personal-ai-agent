"""Gemini compatibility name for the Personal AI LiteLLM gateway."""

from collections.abc import Callable

import httpx

from personal_ai.llm.litellm_gateway import LiteLLMGenerationClient
from personal_ai.settings import Settings


class GeminiLLMClient(LiteLLMGenerationClient):
    """Gemini generation facade; provider SDK details stay in the gateway."""

    def __init__(
        self,
        settings: Settings,
        *,
        async_transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
        sync_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
    ) -> None:
        super().__init__(
            settings,
            "gemini",
            async_transport_factory=async_transport_factory,
            sync_transport_factory=sync_transport_factory,
        )
