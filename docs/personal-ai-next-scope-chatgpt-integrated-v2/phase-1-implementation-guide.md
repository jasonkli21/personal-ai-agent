# Next-scope Phase 1 implementation guide — Application and workspace identity

Status: locally patched and offline-verified; storage-level legacy isolation, the complete scope matrix, and deployed verification remain pending

Date: 2026-10-05

This is **next-scope Phase 1**, distinct from the repository's original Phase 1
chat implementation. It implements the application/workspace identity contract
from the [Phase 1 plan](personal-ai-next-scope-detailed-implementation-plans/plans/phase-1-implementation-plan.md)
without adding application registry or domain features.

## Request contract

`backend/src/personal_ai/auth/scope.py` defines `RequestScope` and
`ApplicationScope`. The authenticated `AuthenticatedPrincipal` supplies
`owner_id`; a caller cannot choose or override it. The canonical application
IDs are `personal_ai`, `travel`, `shopping`, `finance`, and `health`. An
omitted application header means `personal_ai`; `workspace_id` is explicitly
nullable.

The backend accepts scope and correlation metadata in these headers:

| Header | Meaning |
| --- | --- |
| `X-Application-ID` | Canonical application namespace; defaults to `personal_ai`. |
| `X-Workspace-ID` | Optional workspace label, subject to server authorization. |
| `X-Request-ID` | Bounded correlation ID; independent of operation idempotency keys. |
| `X-Client-Capabilities` | Bounded, validated client capability labels; never authority. |
| `X-Client-Context` | Small JSON object of primitive metadata; capped at 4 KiB and never authority. |

Authentication middleware validates this envelope, binds it for the request,
and logs the request ID with application/workspace labels. Workspace requests
are checked through an injected `workspace_authorizer`; the default
`DenyWorkspaceAuthorizer` rejects them. This phase does not establish deployed
workspace membership. Existing Travel and Shopping comparison, proposal, and
extraction APIs remain in the standalone Personal AI namespace until their
application integrations exist.

The Next.js proxy forwards only the allowlisted scope/correlation headers. It
does not forward an owner claim. Frontend helpers in `frontend/src/lib/api.ts`
construct these headers for browser API calls.

## Persisted records and compatibility

`ApplicationScopedRecord` adds `application_id`, nullable `workspace_id`, and
`scope_version`. Missing fields decode as version 1, standalone Personal AI,
and no workspace. New repository writes recursively add the current scope and
write `scope_version: 2`. Aggregate updates retain the v1 scope envelopes of
historical embedded records. No backfill or reassignment of legacy records
occurs.

The scope is persisted across conversations/messages and summaries; original
and derived memory; lifecycle state, events, jobs and worker notifications;
research/evidence and iterative research; canonical entities, claims, matches,
decisions and evaluations; domain comparison results; itinerary proposals; and
booking extraction results. Where identity is deterministic, app/workspace
scope participates in the relevant IDs and idempotency keys. Standalone
document IDs retain their prior form for compatibility.

Repository reads enforce the active scope for both direct-ID and collection
access. Non-standalone Firestore queries prefilter by v2 scope fields. The
standalone compatibility path uses bounded owner scans where legacy records
have no queryable scope fields, then applies standalone/null scope before
returning results. Standalone memory retrieval ranks eligible vectors after
scope filtering instead of allowing foreign vectors to consume a KNN result
cap; it fails closed after 5,000 records or the request deadline. This preserves
legacy recall, but Firestore still reads foreign-scope documents during that
compatibility scan. A zero-foreign-read legacy query requires a separate legacy
data discriminator or storage partition and remains an open isolation item;
no legacy backfill was authorized. Decision entity, alias, and claim lookups,
memory lifecycle candidate/dependency discovery, and booking-extraction expiry
now page through bounded result windows and apply scope before filling their
requested limits. These compatibility scans stop after 5,000 documents or the
request's remaining time. Export pages owner records through the same scope
check and resolves legacy ownerless evaluation/claim-extension rows only
through owner- and scope-checked parent records. Export fails closed at a
100,000-record scan bound.

Conversation listing uses datastore pages, applies scope before filling the
requested result count, and stops at a 5,000-record or five-second bound.
Account deletion intents are account-wide operator workflows and currently
reject non-standalone app/workspace scopes. Chat creation SSE events use the
canonical records returned by persistence; decision inspection envelopes use
the durable decision scope.

Worker notifications carry application/workspace labels as routing metadata.
The worker uses those labels to bind repository scope, then reloads the durable
job and validates the job scope before doing work; notification metadata alone
does not authorize processing. Existing branch ancestry and superseded message
records remain intact, with active-branch replay restricted to the current
scope.

`firestore.indexes.json` contains the additional composite and vector index
definitions needed by scoped Firestore queries. They are checked in but were
not provisioned in a live project as part of this local implementation.

## Operational boundary

The implementation adds no migration or backfill job. Workspace access remains
unavailable until an application installs a real membership authorizer.
Existing domain-specific routes reject non-standalone scope until their
integrations are implemented. Local fake-repository checks do not validate
Firestore emulator behavior, production indexes, Cloud Run IAM, or deployed
proxy identity forwarding. Existing Phase 9 physical deletion, full legacy
owner migration, provider accounting, and release gates remain open.

See the [implementation evidence](phase-1-implementation-evidence-2026-10-05.md)
for exact local checks and remaining verification gaps.
