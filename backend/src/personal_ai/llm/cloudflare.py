"""Cloudflare Workers AI compatibility name for the LiteLLM gateway."""

from collections.abc import Callable

import httpx

from personal_ai.llm.litellm_gateway import LiteLLMGenerationClient
from personal_ai.settings import Settings
from personal_ai.usage.contracts import ProviderUsageAccounting


class CloudflareWorkersAILLMClient(LiteLLMGenerationClient):
    """Workers AI facade with account and credential scope bound per call."""

    def __init__(
        self,
        settings: Settings,
        *,
        async_transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
        sync_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
        usage_accounting: ProviderUsageAccounting | None = None,
    ) -> None:
        super().__init__(
            settings,
            "cloudflare_workers_ai",
            async_transport_factory=async_transport_factory,
            sync_transport_factory=sync_transport_factory,
            usage_accounting=usage_accounting,
        )
