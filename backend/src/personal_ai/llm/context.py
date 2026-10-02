"""Gemini adapters for authoritative counting and bounded summary generation."""

import json
import logging
from collections.abc import Sequence
from typing import Any

from personal_ai.context.assembler import summary_request
from personal_ai.context.contracts import ConversationSummary, SummaryDraft, TokenCount
from personal_ai.entities import Message
from personal_ai.llm.client import ChatMessage
from personal_ai.llm.errors import LLMError
from personal_ai.llm.gemini import (
    GeminiLLMClient,
    _gemini_contents,
    _system_instruction,
    _translate_error,
)
from personal_ai.settings import Settings

logger = logging.getLogger(__name__)


class GeminiTokenCounter:
    def __init__(self, settings: Settings, client: Any = None) -> None:
        self.settings = settings
        self.client = client
        self._owned_client = None
        self._cache: dict[tuple[ChatMessage, ...], TokenCount] = {}

    def count(self, messages: Sequence[ChatMessage]) -> TokenCount:
        return self.count_with_timeout(messages, None)

    def count_with_timeout(
        self, messages: Sequence[ChatMessage], timeout_seconds: float | None,
    ) -> TokenCount:
        key = tuple(messages)
        if key in self._cache:
            return self._cache[key]
        try:
            client = self.client or self._owned_client
            if client is None:
                adapter = GeminiLLMClient(self.settings)
                adapter._validate_request(messages)
                client = adapter._build_client()
                self._owned_client = client
            model = self.settings.ai_model.removeprefix("models/")
            # The locked SDK's public method rejects system_instruction for the
            # Gemini Developer API. Its transport sends the documented REST shape.
            options = {"retry_options": {"attempts": 1}}
            if timeout_seconds is not None:
                options["timeout"] = max(1, int(timeout_seconds * 1000))
            result = client._api_client.request(
                "post",
                f"models/{model}:countTokens",
                {
                    "generateContentRequest": {
                        "model": f"models/{model}",
                        "contents": _gemini_contents(messages),
                        "systemInstruction": {"parts": [{"text": _system_instruction(messages)}]},
                    }
                },
                http_options=options,
            )
            count = json.loads(result.body)["totalTokens"]
            if not isinstance(count, int) or count < 0:
                raise ValueError("invalid provider token count")
            result_count = TokenCount(count, "provider")
            self._cache[key] = result_count
            return result_count
        except LLMError:
            raise
        except Exception as error:
            raise _translate_error(error) from error

    def close(self) -> None:
        client, self._owned_client = self._owned_client, None
        if client is not None:
            try:
                client.close()
            except Exception as error:  # noqa: BLE001 - preserve provider result
                logger.error("Provider client cleanup failed error_class=%s", type(error).__name__)


class GeminiConversationSummarizer:
    def __init__(self, settings: Settings, client: Any = None) -> None:
        self.settings = settings
        self.client = client

    def summarize(
        self,
        source_messages: Sequence[Message],
        prior_summary: ConversationSummary | None,
    ) -> SummaryDraft:
        return self.summarize_with_timeout(source_messages, prior_summary, None)

    def summarize_with_timeout(
        self, source_messages: Sequence[Message], prior_summary: ConversationSummary | None,
        timeout_seconds: float | None,
    ) -> SummaryDraft:
        request = summary_request(source_messages, prior_summary)
        client = self.client
        owns = client is None
        try:
            if owns:
                adapter = GeminiLLMClient(self.settings)
                adapter._validate_request(request)
                client = adapter._build_client()
            options = {"retry_options": {"attempts": 1}}
            if timeout_seconds is not None:
                options["timeout"] = max(1, int(timeout_seconds * 1000))
            result = client.models.generate_content(
                model=self.settings.ai_model,
                contents=_gemini_contents(request),
                config={
                    "system_instruction": _system_instruction(request),
                    "max_output_tokens": self.settings.max_summary_tokens,
                    "http_options": options,
                },
            )
            return SummaryDraft(result.text or "", self.settings.ai_model)
        except LLMError:
            raise
        except Exception as error:
            raise _translate_error(error) from error
        finally:
            if owns and client is not None:
                try:
                    client.close()
                except Exception as error:  # noqa: BLE001 - cleanup preserves the provider result
                    logger.error(
                        "Provider client cleanup failed error_class=%s", type(error).__name__
                    )
