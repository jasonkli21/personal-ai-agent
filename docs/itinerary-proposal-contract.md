# Travel itinerary proposal capability (proposed)

**Status:** proposed for independent review; not yet an accepted inter-repository contract  
**Schema:** `itinerary-proposal-v1`  
**Date:** 2026-10-03

This document proposes a bounded upstream AI capability for the travel
application. The travel application remains authoritative for trip records,
rules, revisions, preview, apply, and deletion. The upstream service returns a
small typed proposal and verified evidence references; it does not read or
write travel storage. This contract must be independently reviewed and pinned
before a travel client enables it.

## HTTP surface

`POST /v1/travel/itinerary-proposals` creates a proposal synchronously. The
caller must be authenticated; the service derives ownership only from the
verified principal. The request uses one UUID idempotency key, a typed immutable
travel projection, a separately supplied user instruction, and up to three
optional owner-scoped `research-v1` session IDs. The session IDs are lookup
inputs only. They are never included in model context or returned as citation
identifiers.

`GET /v1/travel/itinerary-proposals/{proposal_id}` retrieves the saved result
or its safe execution state for the authenticated owner. A missing or
cross-owner ID has the same 404 response. `GET
/v1/travel/itinerary-proposals/by-key/{idempotency_key}` resolves a result for
the authenticated owner after a lost POST response, so the caller does not
need to know or derive the owner-scoped proposal ID.

Requests with the same owner, key, and normalized content replay the same
result. Reusing a key with different content returns 409. A concurrent replay
while a request is running returns 409 with a stable `proposal_busy` code; the
caller can GET by idempotency key. A request whose provider outcome becomes uncertain is
terminal for that key and is never retried implicitly.

## Request schema

The top-level object is strict (`extra=forbid`):

```json
{
  "schema_version": "itinerary-proposal-v1",
  "idempotency_key": "00000000-0000-4000-8000-000000000001",
  "instruction": "Move the market visit to the second day.",
  "research_session_ids": [],
  "context": {
    "schema_version": "travel-itinerary-context-v1",
    "trip_handle": "h_abcdefgh",
    "title": "Lisbon",
    "start_date": "2026-10-10",
    "end_date": "2026-10-12",
    "timezone": "Europe/Lisbon",
    "days": [
      {
        "handle": "h_day00001",
        "day_index": 1,
        "date": "2026-10-10",
        "items": [
          {
            "handle": "h_item0001",
            "label": "Market visit",
            "item_type": "activity",
            "status": "planned",
            "start_time": "10:00",
            "end_time": "11:00",
            "protected": false,
            "removable": false
          }
        ]
      }
    ],
    "candidates": [
      {"handle": "h_cand00001", "label": "Riverside museum"}
    ],
    "removable_item_handles": []
  }
}
```

The example handles are illustrative; production callers supply fresh,
proposal-scoped opaque handles. The projection is complete for its declared
bounded range; over-limit input is rejected rather than silently truncated.
It contains selected labels, dates, timezone, local schedules, status and
protection/removal flags. It has no owner, trip, day, item, place, candidate, or
reservation UUID; no private note, booking confirmation, source reference,
arbitrary URL, or free-form place data. `instruction` is a distinct bounded
field. Unknown fields are rejected.

The input allows no more than 366 inclusive days, 5,000 total existing items,
500 saved candidates, 25 removable-item handles, three research sessions, and
a 262,144-byte request cap. Handles have bounded `h_` syntax, are
unique across all context kinds, and are checked against their declared kind.
Day dates must be contiguous and match the trip range; timezone and local-time
syntax are validated. The travel service remains responsible for its
authoritative schedule/DST and ownership checks.

Removal is permitted only for an item both marked `removable` and named in the
traveler-selected allowlist. Any item marked `protected` is ineligible for
move, time changes, or removal. The upstream check also treats `booked` and
`completed` items as protected. The travel service must derive these flags and
repeat all checks against current SQL state before preview or apply.

## Operation schema

The response operation objects match the travel-side `ProposalOperation`
field shapes and remain strict discriminated objects. There can be at most 25
operations, applied in listed order by the consumer's validator:

```json
{"kind":"add_item","day_handle":"h_day00001","candidate_handle":"h_cand00001","item_type":"activity","position":0,"start_time":null,"end_time":null}
{"kind":"move_item","item_handle":"h_item0001","day_handle":"h_day00001","position":0}
{"kind":"set_item_times","item_handle":"h_item0001","start_time":"10:30"}
{"kind":"remove_item","item_handle":"h_item0001"}
```

Only saved candidate handles can be added. Only existing item handles can be
moved, retimed, or removed. References are opaque handles supplied in this
request, and are validated against the correct kind. Operations cannot set
arbitrary properties, create candidates, edit reservations or places, change
booking state, or contain notes, links, or free-text values. Positions are
checked against the evolving ordered itinerary. The travel service remains the
source of truth for its complete deterministic preview.

## Evidence and response

If `research_session_ids` are supplied, the service resolves each record
through the existing owner-scoped `research-v1` repository. It accepts only
completed, unexpired sessions and selected evidence whose source observations
are accepted, attributable, observed no later than the request, and not expired.
It assigns temporary `e_` handles and supplies those handles, bounded passage
text, and verified observation/expiry timestamps to the model. Source URLs and
source IDs stay out of model context. Model-generated URLs, timestamps,
evidence claims, and source IDs are never trusted. Citations in the returned
envelope are reconstructed from the verified research/evidence records.

The generated JSON contains exactly `schema_version`, `trip_handle`, `status`,
`failure_code`, `operations`, and `operation_support`. `operation_support` maps operation
indexes to zero or more evidence handles. When research evidence was supplied,
every proposed operation must cite at least one supplied, fresh evidence
handle; otherwise the service returns `uncited` with no operations. With no
external evidence supplied, a proposal may be based only on the user's
instruction and the typed trip context. A result needing information absent
from that context must be `insufficient`, with no operations. There is no
free-form model explanation in this first contract.

The public response envelope is:

```json
{
  "schema_version": "itinerary-proposal-v1",
  "proposal_id": "00000000-0000-4000-8000-000000000002",
  "state": "proposed",
  "policy_version": "itinerary-proposal-policy-v1",
  "trip_handle": "h_abcdefgh",
  "operations": [
    {"kind":"add_item","day_handle":"h_day00001","candidate_handle":"h_cand00001","item_type":"activity","position":1,"start_time":null,"end_time":null}
  ],
  "operation_support": [],
  "citations": [],
  "failure_code": null,
  "created_at": "2026-10-03T12:00:00Z",
  "expires_at": "2026-10-04T12:00:00Z"
}
```

States are `running`, `proposed`, `insufficient`, `uncited`, `expired`, and
`failed`. Failure codes come from a fixed safe enum and contain no provider
details. Citation entries contain an `e_` handle, verified public source URL,
bounded title, observation time, and expiry; they contain no research-session,
evidence, or source-observation UUID. The model never sees those URLs or UUIDs.
If a provided session is unavailable, not completed, stale, or has no selected
evidence, generation stops with explicit `insufficient` or `expired` status.
Each citation expires at the earlier of its selected evidence and research
session expiry. If evidence expires while the model call is in flight, no
proposal is returned.

The result expiry is the earliest verified evidence or session expiry used in
model context, capped at 24 hours after creation. Without external evidence it is at
most 24 hours after creation. A replay never extends expiry. The idempotency
record is retained for at most 48 hours so the owner can reconcile an
uncertain response; Firestore TTL may remove it after this bound. The durable
aggregate stores only the normalized request fingerprint, owner, safe state,
typed operations/citations, and bounded timestamps—not raw prompt, trip
snapshot, or provider output.

## Independent gates and limits

The feature gate defaults off. The generator is independently selected as a
credential-free local fake or the existing `LLMClient` Gemini adapter; live
generation requires both its separate provider gate and the existing external
provider kill switch to permit the call. Research, search-provider, and
itinerary-proposal gates do not enable each other. The API rate limiter and
existing conservative daily provider reservation account for one model call
and its configured input-token ceiling. That reservation remains an estimate,
not complete provider billing reconciliation.

The request and response bytes, instruction/context sizes, operation count,
evidence/session count, output tokens, and whole request time are bounded.
Generation has a maximum 45-second deadline to fit within the travel client's
under-50-second whole-call bound. Output is accumulated only to the configured
byte cap and is strict JSON with duplicate-key and unknown-field rejection.
Default telemetry contains request IDs, counts, duration, and safe error
classes only; prompt, context, evidence passage, and provider output are not
logged.

## Persistence and data lifecycle

The production repository uses one owner-scoped `itinerary_proposals`
Firestore aggregate, keyed by a deterministic owner/idempotency digest. A
transaction claims `running` before model dispatch and writes one immutable
terminal result. Concurrent requests cannot dispatch duplicate model calls.
An outcome that is unknown after timeout or storage loss stays unavailable for
that key; callers use GET to reconcile and submit a new key only after making a
new intentional request.

The collection is included in owner export coverage. It is an owner-data
collection subject to the existing deletion-request coverage, whose physical
deletion work remains incomplete. Configure Firestore TTL on
`itinerary_proposals.retained_until` only after reviewing the deployed retention
policy. TTL is a bounded-storage control, not proof of immediate deletion or a
substitute for deletion-aware restore. Proposal result eligibility is checked
against `expires_at` at every read even before TTL removes the aggregate.

## Implementation/review stages

1. Proposed contract and policy: add this document and ADR 0019, with no route
   acceptance claim.
2. Strict vertical capability: typed request/result/operation DTOs, input
   validation, bounded generation through shared context and `LLMClient`,
   verified evidence adaptation, owner-scoped replay repository, gated routes,
   safe errors, and focused tests.
3. Adversarial verification and handoff: exact consumer-shaped fixtures,
   malformed/foreign/stale/expired/oversized/concurrent cases, fake-backed
   HTTP endpoint check, relevant upstream offline evaluations, release
   evidence, and a minimal travel-coordinator checkpoint.

The independent coordinator review decides whether this proposal becomes an
accepted upstream contract and pins a revision. Provider quality, emulator,
cloud, and deployment behavior remain unverified until separately exercised.
