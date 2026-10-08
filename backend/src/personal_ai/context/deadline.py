"""One preparation deadline shared by counting and summary generation."""

from time import monotonic

from personal_ai.llm.errors import LLMInvalidRequestError, LLMTimeoutError


def remaining(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    seconds = deadline - monotonic()
    if seconds <= 0:
        raise LLMTimeoutError("context preparation timed out")
    return seconds


class DeadlineCounter:
    def __init__(
        self, counter, deadline: float | None, inference_context=None, expected_identity=None
    ) -> None:
        self.counter = counter
        self.deadline = deadline
        self.inference_context = inference_context
        self.expected_identity = expected_identity

    def count(self, messages):
        return self.count_with_timeout(messages, None)

    def count_with_timeout(self, messages, timeout_seconds: float | None):
        call_deadline = self.deadline
        if timeout_seconds is not None:
            requested_deadline = monotonic() + max(0.0, timeout_seconds)
            call_deadline = (
                requested_deadline
                if call_deadline is None
                else min(call_deadline, requested_deadline)
            )
        seconds = remaining(call_deadline)
        timed = getattr(self.counter, "count_with_timeout", None)
        if getattr(self.counter, "requires_inference_context", False):
            if timed:
                result = timed(
                    messages, seconds, inference_context=self.inference_context
                )
            else:
                result = self.counter.count(
                    messages, inference_context=self.inference_context
                )
        else:
            result = timed(messages, seconds) if timed else self.counter.count(messages)
        remaining(call_deadline)
        if self.expected_identity is not None and (
            getattr(result, "kind", None) != "provider"
            or getattr(result, "confidence", None) != "authoritative"
            or getattr(result, "provider_id", None) != self.expected_identity.provider_id
            or getattr(result, "model_id", None) != self.expected_identity.model_id
            or getattr(result, "serializer_id", None) != self.expected_identity.serializer_id
        ):
            raise LLMInvalidRequestError("model input counter endpoint mismatch")
        return result


class DeadlineSummarizer:
    def __init__(self, summarizer, deadline: float | None) -> None:
        self.summarizer = summarizer
        self.deadline = deadline

    def summarize(self, source, prior, *, inference_context=None):
        seconds = remaining(self.deadline)
        timed = getattr(self.summarizer, "summarize_with_timeout", None)
        if timed:
            result = (
                timed(source, prior, seconds, inference_context=inference_context)
                if inference_context is not None
                else timed(source, prior, seconds)
            )
        else:
            result = (
                self.summarizer.summarize(
                    source, prior, inference_context=inference_context
                )
                if inference_context is not None
                else self.summarizer.summarize(source, prior)
            )
        remaining(self.deadline)
        return result
