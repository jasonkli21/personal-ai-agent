# Phase 7 implementation guide

Phase 7 travel and shopping comparison modules are implemented locally as of
2026-10-02. `DECISION_ENABLED`, `TRAVEL_ENABLED`, `SHOPPING_ENABLED`, the two
real provider-policy approval flags, and domain inspection default off. The
modules reuse Phase 5 evidence and Phase 6 identity, claim verification,
constraint, and ranking contracts. They do not create bookings, purchases,
authoritative itineraries, or price history.

## Delivered scope

The versioned `domain-module-v1` registrations define entity types, supported
constraints and features, field schemas, source and feature policy versions,
privacy notices, retention policies, and adapter names. Travel and shopping
modules validate their vocabulary, map evidence-backed claims, contribute
typed feature scores only for candidates that passed shared hard constraints,
and render comparison rows from the resulting decision snapshot.

Each persisted comparison retains the Phase 6 decision ID, candidate order,
constraints and preferences, state, policy versions, field schema version,
claim extensions, and provider observation metadata. Firestore details stay
behind the domain repository. Domain claims and provider observations are
written atomically with the comparison view. Reads are owner-scoped and bounded;
the implementation adds no composite Firestore index. Synthetic fixtures cover
missing, stale, conflicting, out-of-radius, wrong-variant, incomplete-cost, and
inconsistent-quoted-total cases.

Provider-backed lookups reserve an owner/domain/idempotency-key fingerprint
before dispatch. The durable reservation stores a hash of the normalized request,
a fence token, state, and—after successful persistence—a pointer to the saved
comparison; it does not retain the raw query. A matching completed retry returns
that comparison without resolving or calling a provider adapter. Reusing the key
with different input conflicts before dispatch. Concurrent reservations return
in-progress, and an outcome that may have crossed a provider boundary is kept
uncertain; neither state silently dispatches the provider again. Known failures
are recorded as safe error metadata for matching retries.

### Travel

Travel constraints cover destination radius, local-date stay windows, party
size, nightly and total budget, a bounded amenity vocabulary, and current
availability. Place lookup maps provider IDs, coordinates, place type, address,
source link, observation time, attribution, and expiry through shared evidence
contracts. The stay-total helper refuses to produce a complete total when taxes
or fees are unknown. Local wall-time conversion uses IANA time zones and
rejects daylight-saving gaps or ambiguous times without an explicit fold.

The Nominatim adapter accepts one explicit place or area query. Its endpoint,
response size, timeout, redirects, request interval, and result count are
bounded. One elapsed deadline covers rate-slot reservation and waiting, the
provider request, and consumption of the full response body. A Firestore
transaction shares request slots across API instances at one request per
second; a slot beyond the remaining deadline is rejected without extending the
queue. Configure `TRAVEL_OSM_USER_AGENT` and
`TRAVEL_OSM_CONTACT_EMAIL`; show the OSM attribution and Nominatim policy notice
before enabling it. Query text is sent to the provider, so users are told not to
include private itinerary details. The default adapter is synthetic and the
provider gate is off.

Nominatim supplies place identity and coordinates only. This phase does not
include hotel, flight, restaurant, or live lodging-availability adapters.
Travel decisions involving dates, rates, or availability add a fail-closed
current-availability requirement independently of caller-supplied availability
preferences; an optional `allow_unknown` requirement cannot weaken it. Place
results alone therefore do not qualify as a bookable or available stay.

### Shopping

Shopping constraints cover product variant and specifications, condition,
merchant, location, complete total price, availability, and delivery date. Each
merchant offer remains a distinct candidate. Variant identity includes
variant-defining attributes and a stable key. Item, shipping, tax, and quoted
total claims remain separate. A `total_price` claim is added only when all cost
components are known, currencies agree, and the normalized component sum
matches the merchant-quoted total. Unknown or inconsistent costs cannot satisfy
a total-budget constraint. Review ratings remain sourced opinions; ranking
uses sample size and freshness as evidence-quality features, not as product
facts.

The Open Food Facts adapter accepts an exact 8–14 digit barcode and requests
only product identity fields. It uses API v3.6, a bounded response, the allowed
staging or production host, a configured descriptive User-Agent, and a shared
Firestore request slot no faster than once every four seconds. Product records
use a thirty-day default TTL and display ODbL/Database Contents License
attribution. The default adapter is synthetic and the real-provider policy gate
is off.

Open Food Facts identifies catalog products; it does not provide the merchant
offers used by the synthetic comparison fixtures. No live merchant offer,
stock, shipping, return-policy, delivery, or review provider is connected.
Shopping decisions independently add a required, fail-closed availability
constraint, so a caller-supplied optional availability constraint cannot
weaken it. A catalog match without a separate fresh offer remains
`research_needed`.

Travel and shopping feature calculations use the shared claim status, scope,
and claim IDs. Conflicting verified/unverified values, stale or retracted
claims, and ambiguous scopes do not contribute to a feature. Travel value
scores compare only the applicable budget basis and currency; without a budget,
only candidates sharing one price basis, scope, and currency are comparable.
Shopping price scores likewise require a shared currency and scope. Incomparable
values are omitted from the score.

### Phase 5 source reuse

The shared domain boundary can map claims backed by a completed Phase 5 session.
Each source observation retains the original URL and selected evidence IDs.
Brave-origin evidence is rejected unless `RESEARCH_ENABLED` is true and the
operator separately asserts `RESEARCH_PROVIDER_STORAGE_APPROVED`; the
provider-rights review remains open. See
[ADR 0015](decisions/0015-phase-7-domain-module-contract.md) and the current
[Brave API terms](https://api-dashboard.search.brave.com/documentation/resources/terms-of-service).

## Configuration

Backend environment settings are listed in [`backend/.env.example`](../backend/.env.example):

- Set `DECISION_ENABLED=true`, then enable `TRAVEL_ENABLED` or
  `SHOPPING_ENABLED` independently.
- Keep `DOMAIN_INSPECTION_ENABLED=false` except in a local development
  environment. Browser inspection also requires its frontend gate.
- Leave the adapter set to `fake` for synthetic comparisons. Selecting
  `osm_nominatim` or `open_food_facts` additionally requires the matching
  provider policy approval and application identity settings.
- Tune the configured provider interval only within its validated floor and
  upper bound; TTLs and request/response bounds have validated limits.
- Frontend server settings are listed in
  [`frontend/.env.local.example`](../frontend/.env.local.example). The Next.js
  proxy checks the decision and per-domain gates before forwarding requests.

The fixed `local` owner is not authentication. Do not use this bootstrap with
private trip, purchase, account, or other personal data.

## API and UI

Routes are in the [API contract](api-contract.md). The gated `/travel` and
`/shopping` pages support provider lookup, runnable synthetic examples, loading
and error states, loading a saved comparison by ID, visible shared constraints,
local eligible/fresh/conflict filters, per-candidate rationale, freshness and
conflict states, and links to original evidence and provider policies. Filters
only change presentation. There are no booking or purchase actions.
The client validates the fields the workbench renders, including exclusion
reasons and provider metadata, and applies the public HTTP(S) link policy to
source and policy links. Invalid responses become recoverable UI errors.

## Evaluation and checks

Run `make domain-eval` for 10 deterministic fixtures: four travel and six
shopping cases. The evaluation checks the decision state, selected candidate,
eligible count, an expected domain field, source references, and that excluded
rows receive no domain ranking features. Run `make backend-test`,
`make backend-lint`, `make context-eval`, `make memory-eval`,
`make memory-lifecycle-eval`, `make research-eval`, `make decision-eval`,
`make frontend-test`, `make frontend-lint`, and `make frontend-typecheck` for
the platform regression set. Dated command results and tested revisions are in
the [Phase 7 release record](releases/phase-7-travel-shopping.md).

## Remaining verification and coverage gaps

- Real Firestore emulator transaction behavior, deployed indexes, and
  multi-instance rate limiting have not been checked. The domain repository
  and provider limiter have offline/fake coverage only.
- Nominatim and Open Food Facts provider smoke tests have not been run. Review
  the current provider policies and attribution requirements before enabling
  either real adapter. No live data quality, coverage, or availability claim is
  implied by the synthetic tests.
- No live hotel/flight/restaurant inventory or merchant offer/availability
  adapter is included. Those fields require a separately reviewed source before
  real travel or shopping recommendations can satisfy their hard requirements.
- Brave storage and AI-use rights, Gemini behavior, deployed proxy behavior,
  and GCP deployment remain unverified. The `local` owner is not an auth
  boundary.

Synthetic evaluations establish deterministic local contract behavior only;
they do not establish provider, emulator, deployment, or commercial-data
rights.
