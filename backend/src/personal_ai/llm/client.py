"""Provider-independent contracts for streamed chat completion."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from personal_ai.entities.conversation import MessageRole


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """A single ordered, active-path chat message supplied to an LLM."""

    role: MessageRole
    content: str


class LLMClient(Protocol):
    """Stream provider-neutral text deltas for an ordered chat history."""

    def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        """Yield text deltas in provider order."""
