"""Credentialed Gemini smoke test, deliberately disabled by default."""

import asyncio
import os

import pytest

from personal_ai.entities.conversation import MessageRole
from personal_ai.llm import ChatMessage, GeminiLLMClient
from personal_ai.settings import Settings


@pytest.mark.skipif(
    os.environ.get("RUN_GEMINI_MANUAL_TEST") != "1",
    reason="Set RUN_GEMINI_MANUAL_TEST=1 with Gemini environment variables to run.",
)
def test_configured_gemini_streams_a_response() -> None:
    settings = Settings()
    client = GeminiLLMClient(settings)

    deltas = asyncio.run(
        _collect(client.stream([ChatMessage(role=MessageRole.USER, content="Reply with hello.")]))
    )

    assert "".join(deltas)


async def _collect(stream):  # type: ignore[no-untyped-def]
    return [delta async for delta in stream]
