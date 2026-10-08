"""Provider-independent contracts for streamed chat completion."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from personal_ai.entities.conversation import MessageRole


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """A single ordered, active-path chat message supplied to an LLM."""

    role: MessageRole | Literal["system"]
    content: str


@dataclass(frozen=True, slots=True)
class InferenceContext:
    """Server-computed sensitivity decision carried to the inference boundary."""

    effective_sensitivity: Literal["public", "personal", "sensitive", "restricted", "unknown"]
    maximum_sensitivity: Literal["public", "personal", "sensitive", "restricted"]
    policy_version: str

    def __post_init__(self) -> None:
        rank = {"public": 0, "personal": 1, "sensitive": 2, "restricted": 3, "unknown": 4}
        if not self.policy_version or rank[self.effective_sensitivity] > rank[self.maximum_sensitivity]:
            raise ValueError("inference_context_not_authorized")


class LLMClient(Protocol):
    """Stream provider-neutral text deltas for an ordered chat history."""

    requires_inference_context: bool

    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        inference_context: InferenceContext | None = None,
    ) -> AsyncIterator[str]:
        """Yield text deltas in provider order."""


SYSTEM_INSTRUCTION = (
    "You are a helpful personal AI chat assistant. "
    "Answer directly and clearly based on this conversation."
)
