# ADR 0013: Use Nominatim for bounded travel place lookup

Date: 2026-10-02

Status: Accepted for the Phase 7 adapter; disabled by default

## Decision

Use OpenStreetMap Nominatim only for an explicit, user-submitted place or area
lookup. Travel keeps source records, typed location claims, constraints, and
ranking inside the Phase 5–6 platform. Nominatim supplies place identity,
coordinates, place type, and a public OpenStreetMap source link. It does not
supply lodging rates, current availability, reservations, or travel-time
guarantees.

The adapter sends one bounded search request to the fixed public endpoint. It
does not provide autocomplete, reverse lookup, area crawling, or background
refresh. Each deployment must identify the application with a configured
User-Agent and contact email. A Firestore transaction reserves request slots
across API instances at no faster than one request per second. Response size,
timeout, result count, redirects, and observation lifetime are bounded.

## Attribution, use, and freshness

- The travel page displays the Nominatim usage-policy link and visible
  “© OpenStreetMap contributors” attribution with the ODbL copyright link.
- Each place fact retains its URL, provider object ID, adapter version,
  observation timestamp, seven-day default expiry, and source-policy URL.
- The page tells users that place text is sent to the provider and asks them
  to keep private itinerary and personal details out of queries.
- Nominatim results do not become proof of current lodging, opening hours,
  accessibility, rates, or availability. Booking-like requests require fresh
  availability evidence through the shared decision constraints.
- Provider data use and caching must follow the current
  [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/)
  and [OpenStreetMap attribution and ODbL terms](https://www.openstreetmap.org/copyright).

## Configuration and fallback

`TRAVEL_ENABLED`, `DECISION_ENABLED`, `TRAVEL_PROVIDER_POLICY_APPROVED`, a
contact email, and a recognizable User-Agent are required before selecting
`TRAVEL_PLACES_ADAPTER=osm_nominatim`. The default adapter is `fake`; failures
return a safe provider error and never fabricate live results. Synthetic
fixtures remain available without a provider request.

## Consequences

The integration is useful for place discovery but has no lodging inventory or
coverage guarantee. Nominatim is not a general geocoding service for private
data. A future provider must get its own policy review and adapter rather than
expanding this endpoint into a broad crawler.
