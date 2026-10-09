"""Shared admission check for bounded model inputs outside chat assembly."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from personal_ai.llm.client import ChatMessage, InferenceContext, TokenCount
from personal_ai.llm.errors import LLMInvalidRequestError


@dataclass(frozen=True, slots=True)
class PreparedModelInput:
    messages: tuple[ChatMessage, ...]
    token_count: TokenCount
    input_limit: int


def require_matching_endpoint(generator, counter) -> None:
    """Fail before counting if the declared counter cannot attest the generator input."""
    if not getattr(generator, "requires_inference_context", False):
        return
    while counter is not None and hasattr(counter, "counter"):
        counter = counter.counter
    generation_identity = getattr(generator, "identity", None)
    counter_identity = getattr(counter, "identity", None)
    capabilities = getattr(counter, "capabilities", None)
    if (
        generation_identity is None
        or counter_identity != generation_identity
        or getattr(counter, "count_confidence", None) != "authoritative"
        or capabilities is None
        or not capabilities.supports("token_counting")
    ):
        raise LLMInvalidRequestError("model input counter endpoint mismatch")


def prepare_bounded_input(
    messages: Sequence[ChatMessage],
    counter,
    *,
    generator,
    input_limit: int,
    timeout_seconds: float | None = None,
    response_schema: Mapping[str, object] | None = None,
    inference_context: InferenceContext | None = None,
    enforce_input_limit: bool = True,
) -> PreparedModelInput:
    """Count the exact endpoint serialization and reject inputs above their ceiling."""
    if not messages or input_limit < 1:
        raise LLMInvalidRequestError("model input bounds are invalid")
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise LLMInvalidRequestError("model input deadline expired")

    generator_identity = getattr(generator, "identity", None)
    counter_identity = getattr(counter, "identity", None)
    if generator_identity is None or counter_identity is None:
        raise LLMInvalidRequestError("model input endpoint identity is required")
    if counter_identity != generator_identity:
        raise LLMInvalidRequestError("model input counter endpoint mismatch")

    count_with_timeout = getattr(counter, "count_with_timeout", None)
    try:
        kwargs = {
            "response_schema": response_schema,
            "inference_context": inference_context,
        }
        if count_with_timeout is not None and timeout_seconds is not None:
            count = count_with_timeout(messages, timeout_seconds, **kwargs)
        else:
            count = counter.count(messages, **kwargs)
    except TypeError as error:
        raise LLMInvalidRequestError("model input counter contract is incomplete") from error
    if count.kind != "provider" or count.confidence != "authoritative":
        raise LLMInvalidRequestError("an authoritative endpoint counter is required")

    if (
        count.provider_id != generator_identity.provider_id
        or count.model_id != generator_identity.model_id
        or count.serializer_id != generator_identity.serializer_id
    ):
        raise LLMInvalidRequestError("model input counter endpoint mismatch")
    if enforce_input_limit and count.tokens > input_limit:
        raise LLMInvalidRequestError("model input exceeds its token budget")
    return PreparedModelInput(tuple(messages), count, input_limit)
