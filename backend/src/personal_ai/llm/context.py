"""Gemini authoritative counting and bounded conversation summarization."""

from collections.abc import Callable, Sequence

import httpx

from personal_ai.context.assembler import summary_request
from personal_ai.context.contracts import ConversationSummary, SummaryDraft
from personal_ai.entities import Message
from personal_ai.llm.client import InferenceContext
from personal_ai.llm.gemini import GeminiLLMClient
from personal_ai.llm.litellm_gateway import LiteLLMTokenCounter
from personal_ai.settings import Settings
from personal_ai.usage.context import bind_usage_task
from personal_ai.usage.contracts import ProviderUsageAccounting


class GeminiTokenCounter(LiteLLMTokenCounter):
    """Authoritative Gemini countTokens seam backed by LiteLLM serialization."""


class GeminiConversationSummarizer:
    def __init__(
        self,
        settings: Settings,
        *,
        sync_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
        usage_accounting: ProviderUsageAccounting | None = None,
    ) -> None:
        self.settings = settings
        self._generator = GeminiLLMClient(
            settings,
            sync_transport_factory=sync_transport_factory,
            usage_accounting=usage_accounting,
        )

    def summarize(
        self,
        source_messages: Sequence[Message],
        prior_summary: ConversationSummary | None,
        *,
        inference_context: InferenceContext | None = None,
    ) -> SummaryDraft:
        return self.summarize_with_timeout(
            source_messages, prior_summary, None,
            inference_context=inference_context,
        )

    def summarize_with_timeout(
        self,
        source_messages: Sequence[Message],
        prior_summary: ConversationSummary | None,
        timeout_seconds: float | None,
        *,
        inference_context: InferenceContext | None = None,
    ) -> SummaryDraft:
        request = summary_request(source_messages, prior_summary)
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else self.settings.request_timeout_seconds
        )
        with bind_usage_task("conversation_summary"):
            result = self.generator.complete(
                request,
                max_output_tokens=self.settings.max_summary_tokens,
                timeout_seconds=timeout,
                inference_context=inference_context,
            ).require_success()
        return SummaryDraft(
            result.text,
            result.metadata.identity.model_id,
            attribution=result.metadata,
        )

    @property
    def generator(self) -> GeminiLLMClient:
        return self._generator
