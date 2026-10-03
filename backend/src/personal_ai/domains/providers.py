"""Bounded, replaceable structured-source adapters for Phase 7 domains."""

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from threading import Lock
from time import monotonic
from typing import Protocol

import httpx
from pydantic import Field, ValidationError

from personal_ai.decisions.contracts import DecisionRecord


class DomainProviderError(Exception):
    def __init__(self, code: str, status: int = 503):
        self.code, self.status = code, status
        super().__init__(code)


class TravelPlaceRecord(DecisionRecord):
    name: str = Field(min_length=1, max_length=300)
    provider_object_id: str = Field(min_length=1, max_length=100)
    osm_type: str = Field(pattern=r"^(node|way|relation)$")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    place_type: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=1000)
    url: str = Field(min_length=1, max_length=2048)


class ShoppingProductRecord(DecisionRecord):
    barcode: str = Field(pattern=r"^\d{8,14}$")
    name: str = Field(min_length=1, max_length=300)
    brand: str | None = Field(default=None, max_length=200)
    quantity: str | None = Field(default=None, max_length=100)
    categories: tuple[str, ...] = Field(default=(), max_length=12)
    url: str = Field(min_length=1, max_length=2048)


class TravelPlaceAdapter(Protocol):
    name: str

    async def lookup(self, query: str, limit: int) -> tuple[TravelPlaceRecord, ...]: ...


class ShoppingProductAdapter(Protocol):
    name: str

    async def lookup_barcode(self, barcode: str) -> ShoppingProductRecord | None: ...


class FakeTravelPlaceAdapter:
    name = "fake"

    def __init__(self, records: tuple[TravelPlaceRecord, ...] = (), error: Exception | None = None):
        self.records, self.error = records, error
        self.calls: list[tuple[str, int]] = []

    async def lookup(self, query: str, limit: int):
        self.calls.append((query, limit))
        if self.error:
            raise self.error
        return self.records[:limit]


class FakeShoppingProductAdapter:
    name = "fake"

    def __init__(self, product: ShoppingProductRecord | None = None, error: Exception | None = None):
        self.product, self.error = product, error
        self.calls: list[str] = []

    async def lookup_barcode(self, barcode: str):
        self.calls.append(barcode)
        if self.error:
            raise self.error
        if self.product is not None and self.product.barcode == barcode:
            return self.product
        return None


class _ProcessRateLimiter:
    def __init__(self):
        self.lock = Lock()
        self.next_request = 0.0


    async def wait(self, interval: float, *, deadline: float) -> None:
        now = monotonic()
        with self.lock:
            slot = max(now, self.next_request)
            if slot >= deadline:
                raise TimeoutError("provider request deadline")
            self.next_request = slot + interval
        delay = max(0.0, slot - monotonic())
        if delay >= max(0.0, deadline - monotonic()):
            raise TimeoutError("provider request deadline")
        await asyncio.sleep(delay)
        if monotonic() >= deadline:
            raise TimeoutError("provider request deadline")


class FirestoreProviderRateLimiter:
    """Reserve provider request slots across app instances using one Firestore record."""

    def __init__(self, client, provider: str):
        self.client, self.provider = client, provider

    async def wait(self, interval: float, *, deadline: float) -> None:
        from google.api_core.exceptions import GoogleAPICallError

        from personal_ai.storage.transactions import bounded_transaction

        reference = self.client.collection("domain_provider_rate_limits").document(self.provider)

        def reserve():
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("provider request deadline")
            now = datetime.now(UTC)

            def operation(transaction, timeout):
                if timeout() <= 0:
                    raise TimeoutError("provider request deadline")
                snapshot = next(transaction.get(reference, retry=None, timeout=timeout()), None)
                next_at = None
                if snapshot is not None and snapshot.exists:
                    raw = snapshot.to_dict().get("next_request_at")
                    if raw:
                        next_at = datetime.fromisoformat(raw).astimezone(UTC)
                slot = max(now, next_at) if next_at is not None else now
                delay = max(0.0, (slot - now).total_seconds())
                if delay >= deadline - monotonic():
                    return None
                transaction.set(reference, {
                    "provider": self.provider,
                    "next_request_at": (slot + timedelta(seconds=interval)).isoformat(),
                })
                return delay

            return bounded_transaction(self.client, operation, seconds=remaining)

        delay = None
        for attempt in range(3):
            if monotonic() >= deadline:
                raise TimeoutError("provider request deadline")
            try:
                delay = await asyncio.to_thread(reserve)
                break
            except TimeoutError:
                raise
            except GoogleAPICallError as error:
                if attempt == 2:
                    raise DomainProviderError("domain_rate_limit_unavailable") from error
                pause = min(0.05 * (attempt + 1), max(0.0, deadline - monotonic()))
                if pause <= 0:
                    raise TimeoutError("provider request deadline") from error
                await asyncio.sleep(pause)
        if delay is None:
            raise TimeoutError("provider request deadline")
        if delay >= max(0.0, deadline - monotonic()):
            raise TimeoutError("provider request deadline")
        await asyncio.sleep(delay)
        if monotonic() >= deadline:
            raise TimeoutError("provider request deadline")


_NOMINATIM_RATE_LIMITER = _ProcessRateLimiter()
_OFF_RATE_LIMITER = _ProcessRateLimiter()


class NominatimPlaceAdapter:
    """User-submitted place lookup; no autocomplete or bulk/area crawling."""

    name = "osm_nominatim"
    endpoint = "https://nominatim.openstreetmap.org/search"

    def __init__(self, settings, transport=None, *, rate_limiter=None):
        self.settings, self.transport = settings, transport
        self.rate_limiter = rate_limiter or _NOMINATIM_RATE_LIMITER

    async def lookup(self, query: str, limit: int):
        if not self.settings.travel_provider_policy_approved:
            raise DomainProviderError("travel_provider_policy_required", 404)
        if not self.settings.travel_osm_contact_email:
            raise DomainProviderError("travel_provider_configuration_invalid", 503)
        if not query.strip() or len(query) > 300 or not 1 <= limit <= self.settings.domain_max_results:
            raise DomainProviderError("travel_lookup_invalid", 422)
        deadline = monotonic() + self.settings.domain_provider_timeout_seconds
        try:
            async with asyncio.timeout_at(deadline):
                await self.rate_limiter.wait(
                    self.settings.travel_min_request_interval_seconds,
                    deadline=deadline,
                )
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("provider request deadline")
                async with (
                    httpx.AsyncClient(
                        timeout=remaining,
                        transport=self.transport,
                        follow_redirects=False,
                        trust_env=False,
                    ) as client,
                    client.stream(
                        "GET",
                        self.endpoint,
                        params={
                            "q": query,
                            "format": "jsonv2",
                            "addressdetails": 1,
                            "limit": limit,
                            "email": self.settings.travel_osm_contact_email,
                        },
                        headers={
                            "Accept": "application/json",
                            "User-Agent": self.settings.travel_osm_user_agent,
                        },
                    ) as response,
                ):
                    if response.status_code == 429:
                        raise DomainProviderError("travel_provider_quota")
                    if response.status_code >= 500:
                        raise DomainProviderError("travel_provider_unavailable")
                    if response.status_code != 200:
                        raise DomainProviderError("travel_provider_rejected")
                    if "application/json" not in response.headers.get("content-type", ""):
                        raise DomainProviderError("travel_provider_invalid_response")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > self.settings.domain_max_response_bytes:
                            raise DomainProviderError("travel_provider_response_oversized")
                        body.extend(chunk)
            payload = json.loads(body)
            if not isinstance(payload, list):
                raise TypeError("invalid response")
            records = []
            for item in payload[:limit]:
                if not isinstance(item, dict):
                    raise TypeError("invalid place")
                osm_type = str(item.get("osm_type", "")).lower()
                osm_id = str(item.get("osm_id", ""))
                if osm_type not in {"node", "way", "relation"} or not osm_id.isdigit():
                    continue
                display_name = item.get("display_name", "")
                name = item.get("name") or display_name
                category = item.get("category", "place")
                place_type = item.get("type", category)
                if any(not isinstance(value, str) for value in (display_name, name, category, place_type)):
                    raise TypeError("invalid place text")
                display_name, name = display_name.strip(), name.strip()
                category, place_type = category.strip(), place_type.strip()
                if not display_name or not name or not place_type:
                    continue
                records.append(
                    TravelPlaceRecord(
                        name=name[:300],
                        provider_object_id=f"{osm_type}/{osm_id}",
                        osm_type=osm_type,
                        latitude=float(item["lat"]),
                        longitude=float(item["lon"]),
                        place_type=f"{category}/{place_type}"[:100],
                        display_name=display_name[:1000],
                        url=f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
                    )
                )
            return tuple(records)
        except DomainProviderError:
            raise
        except httpx.TimeoutException as error:
            raise DomainProviderError("travel_provider_timeout") from error
        except TimeoutError as error:
            raise DomainProviderError("travel_provider_timeout") from error
        except httpx.TransportError as error:
            raise DomainProviderError("travel_provider_unavailable") from error
        except (ValueError, KeyError, TypeError, ValidationError) as error:
            raise DomainProviderError("travel_provider_invalid_response") from error


class OpenFoodFactsAdapter:
    """Exact barcode lookup; images and offer/merchant data are not requested."""

    name = "open_food_facts"

    def __init__(self, settings, transport=None, *, rate_limiter=None):
        self.settings, self.transport = settings, transport
        self.rate_limiter = rate_limiter or _OFF_RATE_LIMITER

    async def lookup_barcode(self, barcode: str):
        if not self.settings.shopping_provider_policy_approved:
            raise DomainProviderError("shopping_provider_policy_required", 404)
        if not barcode.isdigit() or not 8 <= len(barcode) <= 14:
            raise DomainProviderError("shopping_barcode_invalid", 422)
        if not self.settings.shopping_off_user_agent:
            raise DomainProviderError("shopping_provider_configuration_invalid", 503)
        base_url = str(self.settings.shopping_off_base_url).rstrip("/")
        endpoint = f"{base_url}/api/v3.6/product/{barcode}.json"
        headers = {
            "Accept": "application/json",
            "User-Agent": self.settings.shopping_off_user_agent,
        }
        if self.settings.shopping_off_base_url.host == "world.openfoodfacts.net":
            headers["Authorization"] = "Basic " + base64.b64encode(b"off:off").decode("ascii")
        deadline = monotonic() + self.settings.domain_provider_timeout_seconds
        try:
            async with asyncio.timeout_at(deadline):
                await self.rate_limiter.wait(
                    self.settings.shopping_min_request_interval_seconds,
                    deadline=deadline,
                )
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("provider request deadline")
                async with (
                    httpx.AsyncClient(
                        timeout=remaining,
                        transport=self.transport,
                        follow_redirects=False,
                        trust_env=False,
                    ) as client,
                    client.stream(
                        "GET",
                        endpoint,
                        params={"fields": "code,product_name,brands,quantity,categories_tags"},
                        headers=headers,
                    ) as response,
                ):
                    if response.status_code == 429:
                        raise DomainProviderError("shopping_provider_quota")
                    if response.status_code >= 500:
                        raise DomainProviderError("shopping_provider_unavailable")
                    if response.status_code not in {200, 404}:
                        raise DomainProviderError("shopping_provider_rejected")
                    if "application/json" not in response.headers.get("content-type", ""):
                        raise DomainProviderError("shopping_provider_invalid_response")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > self.settings.domain_max_response_bytes:
                            raise DomainProviderError("shopping_provider_response_oversized")
                        body.extend(chunk)
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise TypeError("invalid product response")
            # v3 uses named statuses and returns 404 for an unknown barcode.
            # The older integer v2 status must not mask a broken v3 contract.
            result = payload.get("result")
            if not isinstance(result, dict):
                raise TypeError("invalid product response")
            if (
                response.status_code == 404
                and payload.get("status") == "failure"
                and result.get("id") == "product_not_found"
            ):
                return None
            if (
                response.status_code != 200
                or payload.get("status") not in {"success", "success_with_warnings"}
                or result.get("id") != "product_found"
                or payload.get("errors")
            ):
                raise TypeError("invalid product response")
            product = payload.get("product")
            if not isinstance(product, dict):
                raise TypeError("invalid product")
            product_name = product.get("product_name", "")
            code = product.get("code")
            if not isinstance(product_name, str) or not isinstance(code, str):
                raise TypeError("invalid product identity")
            product_name, code = product_name.strip(), code.strip()
            if not product_name or code != barcode:
                return None
            categories = product.get("categories_tags", ())
            if not isinstance(categories, (list, tuple)) or any(not isinstance(item, str) for item in categories):
                raise TypeError("invalid product categories")
            brand, quantity = product.get("brands"), product.get("quantity")
            if any(value is not None and not isinstance(value, str) for value in (brand, quantity)):
                raise TypeError("invalid product text")
            return ShoppingProductRecord(
                barcode=barcode,
                name=product_name[:300],
                brand=((brand or "").split(",")[0].strip() or None),
                quantity=((quantity or "").strip() or None),
                categories=tuple(item[:100] for item in categories[:12] if item.strip()),
                url=f"https://world.openfoodfacts.org/product/{barcode}",
            )
        except DomainProviderError:
            raise
        except httpx.TimeoutException as error:
            raise DomainProviderError("shopping_provider_timeout") from error
        except TimeoutError as error:
            raise DomainProviderError("shopping_provider_timeout") from error
        except httpx.TransportError as error:
            raise DomainProviderError("shopping_provider_unavailable") from error
        except (ValueError, KeyError, TypeError, ValidationError) as error:
            raise DomainProviderError("shopping_provider_invalid_response") from error
