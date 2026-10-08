"""Groq compatibility name for the Personal AI LiteLLM gateway."""

from collections.abc import Callable

import httpx

from personal_ai.llm.litellm_gateway import LiteLLMGenerationClient
from personal_ai.settings import Settings


class GroqLLMClient(LiteLLMGenerationClient):
    """Groq generation facade; eligibility remains a Personal AI policy."""

    def __init__(
        self,
        settings: Settings,
        *,
        async_transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
        sync_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
    ) -> None:
        super().__init__(
            settings,
            "groq",
            async_transport_factory=async_transport_factory,
            sync_transport_factory=sync_transport_factory,
        )
