"""Shared admission check for bounded model inputs outside chat assembly."""

from collections.abc import Sequence
from dataclasses import dataclass

from personal_ai.llm.client import ChatMessage, TokenCount
from personal_ai.llm.errors import LLMInvalidRequestError


@dataclass(frozen=True, slots=True)
class PreparedModelInput:
    messages: tuple[ChatMessage, ...]
    token_count: TokenCount
    input_limit: int


def prepare_bounded_input(
    messages: Sequence[ChatMessage],
    counter,
    *,
    input_limit: int,
    timeout_seconds: float | None = None,
) -> PreparedModelInput:
    """Count the exact endpoint serialization and reject inputs above their ceiling."""
    if not messages or input_limit < 1:
        raise LLMInvalidRequestError("model input bounds are invalid")
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise LLMInvalidRequestError("model input deadline expired")

    count_with_timeout = getattr(counter, "count_with_timeout", None)
    count = (
        count_with_timeout(messages, timeout_seconds)
        if count_with_timeout is not None and timeout_seconds is not None
        else counter.count(messages)
    )
    if count.kind != "provider":
        raise LLMInvalidRequestError("an authoritative endpoint counter is required")

    identity = getattr(counter, "identity", None)
    if identity is not None and (
        count.provider_id != identity.provider_id
        or count.model_id != identity.model_id
        or count.serializer_id != identity.serializer_id
    ):
        raise LLMInvalidRequestError("model input counter identity mismatch")
    if count.tokens > input_limit:
        raise LLMInvalidRequestError("model input exceeds its token budget")
    return PreparedModelInput(tuple(messages), count, input_limit)
