import asyncio

import httpx
import pytest

from personal_ai.search.providers import brave
from personal_ai.search.providers.brave import BraveSearchAdapter, SearchError
from personal_ai.settings import Settings


@pytest.fixture
def anyio_backend():
    return "asyncio"


def adapter(response):
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="test",
        research_enabled=True,
        research_search_adapter="brave",
        research_provider_storage_approved=True,
        research_api_key="synthetic-secret",
        research_brave_prepaid_verified=True,
        research_brave_auto_reload_disabled=True,
        research_brave_no_paid_balance_verified=True,
        research_brave_source_rights_verified=True,
        research_brave_account_scope_id="synthetic-brave-account",
        research_brave_preflight_reference="operator-preflight:synthetic-brave",
    )
    brave._NEXT_REQUEST = 0

    def transport(request):
        assert request.url.host == "api.search.brave.com"
        assert request.headers["X-Subscription-Token"] == "synthetic-secret"
        return response(request) if callable(response) else response

    return BraveSearchAdapter(settings, transport=httpx.MockTransport(transport))


@pytest.mark.anyio
async def test_snippet_response_and_no_source_fetch():
    value = adapter(
        httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "url": "https://example.org/test",
                            "title": "Title",
                            "description": "Snippet",
                        },
                    ]
                }
            },
        )
    )
    results = await value.search("Synthetic query", 1)
    assert results[0].text == "Snippet" and results[0].published_at is None
    assert "synthetic-secret" not in repr(value.settings)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response,code",
    [
        (httpx.Response(429), "search_quota"),
        (httpx.Response(503), "search_unavailable"),
        (httpx.Response(302, headers={"location": "http://localhost/"}), "search_rejected"),
        (httpx.Response(200, json={"web": {"results": "wrong"}}), "search_invalid_response"),
        (
            httpx.Response(200, json={"web": {"results": [{"url": None}]}}),
            "search_invalid_response",
        ),
        (
            httpx.Response(200, content="x", headers={"content-type": "text/html"}),
            "search_invalid_response",
        ),
        (
            httpx.Response(
                200, content=b"x" * 131073, headers={"content-type": "application/json"}
            ),
            "search_response_oversized",
        ),
    ],
)
async def test_provider_failure_mapping(response, code):
    with pytest.raises(SearchError, match=code):
        await adapter(response).search("Synthetic query", 1)


@pytest.mark.anyio
async def test_timeout_empty_and_malformed_json():
    def timeout(request):
        raise httpx.ReadTimeout("secret detail")

    with pytest.raises(SearchError, match="search_timeout"):
        await adapter(timeout).search("Synthetic query", 1)
    assert await adapter(httpx.Response(200, json={})).search("Synthetic query", 1) == ()
    with pytest.raises(SearchError, match="search_invalid_response"):
        await adapter(
            httpx.Response(200, content="{", headers={"content-type": "application/json"})
        ).search("Synthetic query", 1)


@pytest.mark.anyio
async def test_rate_wait_is_cancellable_and_no_request_is_sent():
    value = adapter(httpx.Response(200, json={}))
    brave._NEXT_REQUEST = brave.monotonic() + 10
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await value.search("Synthetic query", 1)
    brave._NEXT_REQUEST = 0
