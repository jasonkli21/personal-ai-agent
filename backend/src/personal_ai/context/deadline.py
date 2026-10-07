"""One preparation deadline shared by counting and summary generation."""

from time import monotonic

from personal_ai.llm.errors import LLMTimeoutError


def remaining(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    seconds = deadline - monotonic()
    if seconds <= 0:
        raise LLMTimeoutError("context preparation timed out")
    return seconds


class DeadlineCounter:
    def __init__(self, counter, deadline: float | None) -> None:
        self.counter = counter
        self.deadline = deadline

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
        result = timed(messages, seconds) if timed else self.counter.count(messages)
        remaining(call_deadline)
        return result


class DeadlineSummarizer:
    def __init__(self, summarizer, deadline: float | None) -> None:
        self.summarizer = summarizer
        self.deadline = deadline

    def summarize(self, source, prior):
        seconds = remaining(self.deadline)
        timed = getattr(self.summarizer, "summarize_with_timeout", None)
        result = timed(source, prior, seconds) if timed else self.summarizer.summarize(source, prior)
        remaining(self.deadline)
        return result
