"""Groq reference adapter over its OpenAI-compatible chat endpoint."""

from collections.abc import Mapping

import httpx

from personal_ai.llm.openai_compatible import OpenAICompatibleGenerationClient
from personal_ai.settings import Settings


class GroqLLMClient(OpenAICompatibleGenerationClient):
    """Bounded streaming and structured generation for a preflighted Groq model."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        async_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            settings,
            provider_id="groq",
            model_id=settings.groq_model,
            serializer_id="groq-chat-completions-v1",
            endpoint="https://api.groq.com/openai/v1/chat/completions",
            api_key=settings.groq_api_key.get_secret_value(),
            adapter_enabled=settings.groq_adapter_enabled,
            free_tier_verified=settings.groq_free_tier_verified,
            privacy_approved=settings.groq_privacy_approved,
            privacy_max_sensitivity=settings.groq_privacy_max_sensitivity,
            approved_model_aliases=settings.groq_approved_model_aliases,
            structured_output_verified=settings.groq_structured_output_verified,
            preflight_reference=settings.groq_preflight_reference,
            client=client,
            async_client=async_client,
        )

    def _max_output_field(self) -> str:
        return "max_completion_tokens"

    def _structured_format(self, schema: Mapping[str, object]) -> Mapping[str, object]:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "personal_ai_response",
                "strict": False,
                "schema": dict(schema),
            },
        }
