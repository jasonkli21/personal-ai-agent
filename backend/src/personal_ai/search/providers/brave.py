"""Brave web-search snippets only. Never fetch source URLs or raw page bodies."""

import asyncio
import json
from threading import Lock
from time import monotonic

import httpx
from pydantic import ValidationError

from personal_ai.agents.research.contracts import ResearchError
from personal_ai.search.contracts import SearchResult

_RATE_LOCK = Lock()
_NEXT_REQUEST = 0.0


class SearchError(ResearchError):
    def __init__(self, code: str, retryable: bool = False):
        super().__init__(code)
        self.retryable = retryable


class BraveSearchAdapter:
    name = "brave"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, settings, transport=None):
        self.settings, self.transport = settings, transport

    async def search(self, query: str, limit: int):
        if (
            not self.settings.research_enabled
            or not self.settings.research_provider_storage_approved
            or not self.settings.research_api_key.get_secret_value()
        ):
            raise SearchError("research_configuration_invalid")
        if not query.strip() or len(query) > 500 or not 1 <= limit <= 12:
            raise SearchError("search_invalid_request")
        global _NEXT_REQUEST
        with _RATE_LOCK:
            slot = max(monotonic(), _NEXT_REQUEST)
            _NEXT_REQUEST = slot + self.settings.research_min_request_interval_seconds
        await asyncio.sleep(max(0, slot - monotonic()))
        try:
            async with (
                httpx.AsyncClient(
                    timeout=self.settings.research_provider_timeout_seconds,
                    transport=self.transport,
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
                client.stream(
                    "GET",
                    self.endpoint,
                    params={"q": query, "count": limit},
                    headers={
                        "X-Subscription-Token": self.settings.research_api_key.get_secret_value(),
                        "Accept": "application/json",
                        "User-Agent": "personal-ai-research/1",
                    },
                ) as response,
            ):
                if response.status_code == 429:
                    raise SearchError("search_quota")
                if response.status_code >= 500:
                    raise SearchError("search_unavailable", retryable=True)
                if response.status_code != 200:
                    raise SearchError("search_rejected")
                if "application/json" not in response.headers.get("content-type", ""):
                    raise SearchError("search_invalid_response")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > self.settings.research_max_response_bytes:
                        raise SearchError("search_response_oversized")
                    content.extend(chunk)
            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise TypeError("invalid response")
            web = payload.get("web", {})
            if not isinstance(web, dict) or not isinstance(web.get("results", []), list):
                raise TypeError("invalid response")
            results = []
            for value in web.get("results", [])[:limit]:
                if not isinstance(value, dict):
                    raise TypeError("invalid result")
                results.append(
                    SearchResult(
                        url=value["url"],
                        title=value.get("title"),
                        text=value.get("description", ""),
                    )
                )
            return tuple(results)
        except httpx.TimeoutException as error:
            raise SearchError("search_timeout", retryable=True) from error
        except httpx.TransportError as error:
            raise SearchError("search_unavailable", retryable=True) from error
        except (ValueError, KeyError, TypeError, ValidationError) as error:
            raise SearchError("search_invalid_response") from error
