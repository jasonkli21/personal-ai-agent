"""Explicit construction of the small set of Phase 17 reference adapters."""

from typing import Literal

from personal_ai.llm.cloudflare import CloudflareWorkersAILLMClient
from personal_ai.llm.errors import LLMInvalidConfigurationError
from personal_ai.llm.gemini import GeminiLLMClient
from personal_ai.llm.groq import GroqLLMClient
from personal_ai.settings import Settings

ProviderName = Literal["gemini", "groq", "cloudflare_workers_ai"]


def build_generation_adapter(
    settings: Settings,
    provider: ProviderName | None = None,
):
    """Construct one explicitly named adapter; this is not a router or registry."""
    selected = provider or settings.ai_provider.lower()
    if selected == "gemini":
        return GeminiLLMClient(settings)
    if selected == "groq":
        return GroqLLMClient(settings)
    if selected == "cloudflare_workers_ai":
        return CloudflareWorkersAILLMClient(settings)
    raise LLMInvalidConfigurationError("configured language model provider is unsupported")
