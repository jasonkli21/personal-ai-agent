"""Cloudflare Workers AI reference adapter using its OpenAI-compatible endpoint."""

from collections.abc import Mapping
from urllib.parse import quote

import httpx

from personal_ai.llm.openai_compatible import OpenAICompatibleGenerationClient
from personal_ai.settings import Settings


class CloudflareWorkersAILLMClient(OpenAICompatibleGenerationClient):
    """Bounded streaming and model-gated JSON-schema generation for Workers AI."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        async_client: httpx.AsyncClient | None = None,
    ) -> None:
        account = quote(settings.cloudflare_account_id, safe="")
        super().__init__(
            settings,
            provider_id="cloudflare_workers_ai",
            model_id=settings.cloudflare_model,
            serializer_id="cloudflare-workers-ai-chat-v1",
            endpoint=(
                "https://api.cloudflare.com/client/v4/accounts/"
                f"{account}/ai/v1/chat/completions"
            ),
            api_key=settings.cloudflare_api_token.get_secret_value(),
            adapter_enabled=settings.cloudflare_adapter_enabled,
            free_tier_verified=settings.cloudflare_free_tier_verified,
            privacy_approved=settings.cloudflare_privacy_approved,
            privacy_max_sensitivity=settings.cloudflare_privacy_max_sensitivity,
            approved_model_aliases=settings.cloudflare_approved_model_aliases,
            structured_output_verified=settings.cloudflare_structured_output_verified,
            preflight_reference=settings.cloudflare_preflight_reference,
            client=client,
            async_client=async_client,
        )

    def _max_output_field(self) -> str:
        return "max_tokens"

    def _structured_format(self, schema: Mapping[str, object]) -> Mapping[str, object]:
        # Workers AI JSON Mode accepts the schema directly; unlike Groq, it does
        # not wrap the schema with a name/strict envelope.
        return {"type": "json_schema", "json_schema": dict(schema)}
