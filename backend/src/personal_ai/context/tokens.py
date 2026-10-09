"""Deterministic conservative estimates for offline work and inspection."""

from collections.abc import Sequence
from math import ceil

from personal_ai.context.contracts import TokenCount
from personal_ai.llm.client import SYSTEM_INSTRUCTION, ChatMessage


class EstimatedTokenCounter:
    """UTF-8 byte upper estimate plus message overhead; never an exact count."""

    counter_version = "estimated-byte-upper-v1"

    def __init__(self, safety_factor: float = 1.1) -> None:
        if safety_factor < 1:
            raise ValueError("estimator safety factor must be at least one")
        self.safety_factor = safety_factor

    def count(self, messages: Sequence[ChatMessage]) -> TokenCount:
        size = len(SYSTEM_INSTRUCTION.encode()) + sum(len(m.content.encode()) + 8 for m in messages)
        return TokenCount(ceil(size * self.safety_factor), "estimated")


class FakeTokenCounter:
    """Exact deterministic word units for fixture budget tests, labelled estimated."""

    def count(self, messages: Sequence[ChatMessage]) -> TokenCount:
        return TokenCount(10 + sum(len(m.content.split()) + 2 for m in messages), "estimated")
