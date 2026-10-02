# ADR 0014: Use Open Food Facts for exact-barcode product identity

Date: 2026-10-02

Status: Accepted for the Phase 7 adapter; disabled by default

## Decision

Use Open Food Facts only for a user-submitted exact barcode lookup. Request
product identity fields needed for comparison and omit images and other
unneeded catalog fields. Product identity is separate from merchant offers,
shipping, delivery, stock, and reviews. Open Food Facts does not provide those
offer facts in this integration.

The adapter uses API v3.6, bounds the response, does not follow redirects, and
reserves one request every four seconds through a shared Firestore rate-limit
record. The setting accepts the Open Food Facts staging or production host; the
default base URL is staging. The staging basic-auth behavior and provider
User-Agent stay inside the adapter.

## Attribution, use, and freshness

- The shopping page states that product data comes from Open Food Facts and is
  user-contributed, with links to the API and legal guide.
- Product observations retain the exact barcode, source URL, provider,
  adapter version, observation timestamp, and thirty-day default expiry.
- Display attribution identifies the database as ODbL-licensed and individual
  contents as Database Contents License material, following the current
  [Open Food Facts API documentation](https://openfoodfacts.github.io/openfoodfacts-server/api/)
  and [license guide](https://openfoodfacts.github.io/openfoodfacts-server/api/tutorials/license-be-on-the-legal-side/).
- Catalog records are not treated as verified merchant facts, current price,
  availability, delivery, or compatibility unless a separate source supports
  those claims.

## Configuration and fallback

`SHOPPING_ENABLED`, `DECISION_ENABLED`, `SHOPPING_PROVIDER_POLICY_APPROVED`,
and a descriptive `SHOPPING_OFF_USER_AGENT` are required before selecting
`SHOPPING_PRODUCTS_ADAPTER=open_food_facts`. The default adapter is `fake`.
Barcode matching is exact; no title-only product merge or offer lookup is
performed.

## Consequences

The integration can identify a catalog product but cannot satisfy the
availability requirement for a current merchant offer. The shopping decision
therefore returns `research_needed` until a separate, permitted offer source
provides fresh price, complete cost, availability, and delivery evidence.
