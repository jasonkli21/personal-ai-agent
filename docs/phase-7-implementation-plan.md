# Phase 7 implementation plan

This plan validates the shared Phase 5–6 platform with thin travel and shopping
modules and synthetic data. It does not create separate rich applications.
Future travel and shopping apps may live in other repositories, own their
authoritative domain records and UI, and consume explicit core APIs. In-core
modules reuse research sessions, evidence, entities, constraints, ranking, and
evaluation.

## Scope boundary

Phase 7 adds domain schemas, source-adapter configurations, typed constraints/features, comparison views, and end-to-end evaluations for travel and shopping. Begin with general web search and structured place/product data that is licensed and permitted. It excludes iterative research, checkout/booking, price tracking, user authentication, broad scraping, and a general marketplace.

## Delivery conventions and cross-cutting requirements

- Each domain uses the internal Phase 7 `DomainModule` contract;
  it may add typed vocabulary, mappings, constraints, features, fixture data,
  and rendering—not its own search, storage, entity, ranking, or auth stack.
  This is an internal AI-side module contract, not an external application
  manifest or generic plugin registry.
- An evidence-backed itinerary candidate or proposal is not the authoritative
  editable itinerary, booking, or reservation record of a future travel app.
- Separate stable identity from variant/offer/visit facts. A hotel room rate,
  flight itinerary, merchant offer, product variant, delivery date, review, or
  opening hour remains an attributable, expiring claim and must never become a
  durable product/place attribute by convenience.
- Make each provider integration independently enabled, rate-limited,
  attributable, and replaceable. Before coding it, record permitted use,
  coverage gaps, attribution/display requirements, IDs available for matching,
  data freshness, and fallback behavior.
- Keep request constraints structured and visible. Domain parsing can propose
  a normalized value but must ask/return ambiguity when the user supplied an
  irreconcilable date, location, currency, party size, variant, compatibility,
  or budget requirement.
- Treat reviews as sourced opinions and aggregate/quality signals, never as
  direct proof of a factual claim. Preserve sample/recency/source limitations.
- Build UI states from validated decision results, not model prose. Evidence
  links open their source; comparison labels state freshness and missing data;
  UI never displays "book", "buy", or a transactional call to action.

## Required verification matrix

In addition to platform regression tests, cover domain registration, source
mapping, place/product/variant identity, currency and time-zone boundaries,
offer expiry, compatibility/dimensions, delivery/availability uncertainty,
review attribution, filters, comparison rendering, mobile/accessibility, and
provider-disabled fallback. Run all automated cases on synthetic data; a manual
provider smoke test must not make a booking, purchase, or persist private trip
or shopping history.

## Required implementation artifacts

P7.1 must add accepted provider/source-policy ADRs, a versioned
`DomainModule` contract, typed domain schemas, adapter fakes, fixture
registries, route/UI state contracts, and migrations/index definitions before
an adapter is enabled. A domain module supplies mappings and presentation
only; the Phase 5 source/evidence path and Phase 6 entity/constraint/ranking
path remain the sole authority for provenance and eligibility.

**Required persisted records:**

| Record | Required fields |
| --- | --- |
| Domain registration | `domain_id`, `schema_version`, `supported_entity_types`, `supported_constraints`, `supported_features`, `source_policy_version`, `enabled` |
| Domain claim extension | `claim_id`, `domain_id`, `attribute`, `typed_value`, `original_value`, `evidence_ids`, `observed_at`, `expires_at`, `schema_version` |
| Provider observation extension | `source_observation_id`, `provider`, `provider_object_id` (nullable), `entity_kind`, `adapter_version`, `attribution`, `observed_at`, `expires_at` |
| Comparison view snapshot | `id`, `decision_id`, `domain_id`, `candidate_ids`, `field_schema_version`, `rendered_at`, `state` |

**Required configuration:**

| Setting | Purpose |
| --- | --- |
| `TRAVEL_ENABLED` / `SHOPPING_ENABLED` | Independent domain gates, disabled until policy review |
| `TRAVEL_*_ADAPTER` / `SHOPPING_*_ADAPTER` | Named permitted provider adapters with fake defaults |
| `TRAVEL_OFFER_TTL_*` / `SHOPPING_OFFER_TTL_*` | Explicit freshness policy for mutable offers |
| `DOMAIN_MAX_RESULTS` / `DOMAIN_MAX_COMPARISON_ROWS` | Bound provider mapping and UI work |
| `DOMAIN_INSPECTION_ENABLED` | Read-only development-only source/decision inspection gate |

## Dependency map

```text
P7.0 Fixtures ─> P7.1 Shared domain contracts ─┬─> P7.2 Travel model/adapters ─> P7.3 Travel constraints/ranking ─┐
                                                └─> P7.4 Shopping model/adapters -> P7.5 Shopping constraints/ranking ─┼─> P7.6 UI ─> P7.7 Verify
P5 research + P6 decisions ───────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 7 — Travel and shopping agents

### P7.0 — Establish domain fixtures and shared-platform baselines

**Dependencies:** Phase 6 completion review

**Goal:** validate reuse without real providers or commercial data.

**Work:** create synthetic travel fixtures for destination, date window, party, budget, hotel/place/restaurant alternatives, and an itinerary gap; create shopping fixtures for a product category, specification, merchant offer, delivery/return conditions, duplicates, and stale price. Specify evidence, entities, constraints, expected comparison rows, and citations.

**Requirements:** identify the source-policy/TTL assumptions for every fixture;
use shared entity and decision IDs only through the public Phase 6 contracts;
include explicit expected `research needed`/`no verified match` cases, not only
successful recommendations.

**Acceptance criteria:** the same Phase 5–6 harness can execute both fixture families; no fixture relies on live availability, reviews, maps, or personal itineraries.

### P7.1 — Define thin-domain extension contracts

**Dependencies:** P7.0

**Decision required:** yes

**Goal:** prevent domain code from duplicating platform logic.

**Work:** document a `DomainModule` contract for schemas, extraction mapping, constraint parsers, feature calculators, display labels, source policy, and fixture registry. Decide approved initial providers, attribution/display rules, cache/TTL rules, geography/currency handling, and explicitly prohibit booking/purchasing actions.

**Requirements:** domain registration validates unique field names, schema
version compatibility, safe defaults, and declared privacy/retention behavior;
the shared platform must be able to load no domain, one domain, or both without
cross-domain assumptions.

**Acceptance criteria:** domains can add typed fields without changing research/evidence/entity core interfaces; provider secrets and terms stay adapter-local.

**Out of scope:** a second domain-specific persistence/ranking stack,
unregistered fields, provider SDK types crossing a domain boundary, or a
transaction provider contract.

### P7.2 — Implement the travel data model and incremental adapters

**Dependencies:** P7.1

**Goal:** represent places, neighborhoods, hotels, flights, restaurants, and proposed itinerary items as evidence-backed candidates, not authoritative trip state.

**Work:** add typed travel claims and mappings from general search plus one permitted structured place-data adapter; normalize coordinates, place/provider IDs, dates, currencies, and travel-specific TTLs. Treat flight/hotel availability/prices as short-lived observations.

**Requirements:** use a canonical time-zone source for local dates/opening
hours; distinguish destination/area/property/room/flight-leg identity; do not
derive total trip cost from partial components without labelling it incomplete.

**Acceptance criteria:** tests cover entity aliases, place ambiguity, expired availability, source attribution, and adapter failure with a usable research fallback.

**Out of scope:** live itinerary reservation, background fare monitoring,
unbounded map crawling, or assumptions about accessible transport.

### P7.3 — Implement travel constraints, features, and result composition

**Dependencies:** P7.2

**Goal:** make travel decisions constraint-safe and explainable.

**Work:** add date-window, party-size, total/night budget, distance/area, opening-hours, amenity, transit-time, and itinerary feasibility constraints; add transparent features such as location fit, value, amenities, and preference match only after eligibility. Compose a bounded itinerary as a proposal with gaps/conflicts, not a booking plan.

**Requirements:** distinguish requested travel dates from flexible date
preferences; apply distance/travel-time only when the underlying point/time
assumptions are known; itinerary composition cannot infer reservations,
operating hours, transfer feasibility, or prices that lack current evidence.

**Acceptance criteria:** tests prove date/time-zone and total-price calculations, no recommendation without current required availability, and itinerary claims retain citations.

**Out of scope:** booking, route purchase, claims of real-time itinerary
feasibility, or filling missing travel facts with model inference.

### P7.4 — Implement the shopping data model and incremental adapters

**Dependencies:** P7.1

**Goal:** represent products, specifications, offers, merchants, and reviews without conflating them.

**Work:** add typed product/specification/offer/merchant/review claims; integrate general search plus permitted structured product data incrementally; normalize model numbers, variants, condition, currency, tax/shipping disclosure, delivery dates, and offer TTLs.

**Requirements:** product identity must include variant-defining attributes
where relevant; merchant offers cannot be merged solely on product title;
review extraction records source, date when available, and whether a rating is
provider-supplied or an application calculation.

**Acceptance criteria:** tests prove variant-aware entity resolution, separate offers for one product, stale offer exclusion, merchant attribution, and graceful adapter failure.

**Out of scope:** inventory purchase, affiliate/tracking behavior, price
history, or merging variants/offers on title similarity.

### P7.5 — Implement shopping constraints, features, and comparisons

**Dependencies:** P7.4

**Goal:** rank eligible products and offers transparently.

**Work:** add budget, required specification, compatibility, size/dimensions, condition, seller location, delivery deadline, return-policy, and merchant constraints. Rank only eligible candidates using explainable value, specification fit, delivery, merchant/review evidence quality, and user preferences.

**Requirements:** normalize total cost only when its components and applicable
currency/date are known; require exact compatibility/variant evidence where a
wrong item would defeat the request; display merchant/review signals as
features, never unqualified seller or product facts.

**Acceptance criteria:** a product never passes based on a different variant or unavailable offer; unknown shipping/returns are labelled; comparisons preserve source links and exclusion reasons.

**Out of scope:** checkout, seller guarantees, opaque review scoring, or a
preference override of a required compatibility/safety constraint.

### P7.6 — Build evidence, comparison, filter, and rationale views

**Dependencies:** P7.3, P7.5

**Goal:** make the platform’s decision process inspectable in the UI.

**Work:** add domain-neutral evidence drawer, candidate comparison table, active filters/constraints, freshness/conflict badges, source links, and per-candidate rationale; layer travel/shopping field renderers on top. Keep research status accessible and avoid presenting results as guaranteed availability.

**Requirements:** preserve raw source attribution rather than linking to a
generated summary; do not expose owner-private memory in comparison or
inspection panels; filter changes are local presentation until a new validated
research/decision request is made.

**Acceptance criteria:** frontend tests cover loading, empty, insufficient-evidence, stale/conflict, filtered, and source-link states; accessibility and mobile layouts preserve rationale and citations.

**Out of scope:** rendering hidden model reasoning, silently re-running
research from a filter interaction, or a transactional UI.

### P7.7 — Evaluate, document, and verify Phase 7

**Dependencies:** P7.0–P7.6

**Goal:** prove that two domains reuse the platform instead of bypassing it.

**Work:** run cross-domain deterministic evaluations; document schemas, providers, attribution, TTLs, user-facing limitations, and adapter setup; test request-to-UI flows using fakes.

**Requirements:** report results per domain and shared-platform version so a
domain-specific improvement cannot mask a shared regression; provider smoke
tests use only permitted synthetic queries and record no raw results by default.

**Acceptance criteria:** clean offline CI proves both domains enforce Phase 6 constraints before ranking, preserve evidence and uncertainty, and share platform components; no bookings, purchases, authentication, or Phase 8 iterative behavior is added.

**Implementation handoff:** document domain registration, supported fields,
provider settings/TTLs, known coverage gaps, fixture commands, and UI state
contracts. These provide the starting point for Phase 8 to assess evidence
gaps without encoding travel or shopping behavior in the shared loop.

## Phase 7 completion review

Before declaring Phase 7 done, verify all task acceptance criteria and answer:

1. Do travel and shopping reuse the same evidence, entity, constraint, and ranking boundaries?
2. Are every price, availability, review, and recommendation appropriately attributed and fresh enough for its use?
3. Can users compare candidates, filters, evidence, and rationale without reading hidden model reasoning?

4. Do fixtures prove variant/place identity safety and constraint-first behavior?
5. Has the phase avoided transactions, broad scraping, and iterative research?

## Implementation status — 2026-10-02

The offline Phase 7 implementation is delivered. Both domains use the shared
Phase 5–6 evidence and decision path; registrations, provider observation and
claim extensions, comparison snapshots, routes, workbench views, fake adapters,
and 10 synthetic fixtures are implemented. The release record
[`phase-7-travel-shopping.md`](releases/phase-7-travel-shopping.md) records
the tested revision and offline results.

The implementation is intentionally bounded by the available approved source
surface: Nominatim supplies place identity/location, Open Food Facts supplies
exact-barcode product identity, and synthetic data exercises stay and merchant
offer decisions. It has no live hotel, flight, restaurant, merchant-offer,
stock, shipping, return-policy, or review adapter. Those facts remain unknown
without fresh source evidence and cannot satisfy the corresponding fail-closed
requirements. Real provider, Firestore emulator, and deployment checks remain
open. This is the external-verification boundary for the completion review, not
evidence that a provider lookup can support a booking or purchase.

Only after all answers are yes should work advance to Phase 8.
