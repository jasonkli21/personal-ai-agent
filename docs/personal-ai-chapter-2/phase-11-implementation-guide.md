# Phase 11 implementation guide — Context source and provider abstraction

Phase 11 adds a typed provider boundary for preparing bounded context from
registered sources. It retains application and workspace scope, source identity,
typed payloads, provenance, authority, sensitivity, timestamps, source
references, and permission dependencies. See the [implementation evidence](phase-11-implementation-evidence.md)
for tested revision and verification status.

## Runtime contracts

- [`context/providers.py`](../../backend/src/personal_ai/context/providers.py)
  defines source classes, typed context items, provider operations, selections,
  results, bounded failures, and the coordinator. The coordinator resolves
  registered capabilities and validates universal target/entity scope for the
  complete selection set before optional availability or unsupported-operation
  handling. It validates operation fields, time windows, result count, response
  bytes, timeout allowance, and read-only tool registration before provider
  fetch. The assembler's absolute request deadline caps every source deadline
  and is checked between sources and before preparation returns. Empty required
  sources fail preparation and stop later optional reads.
- Every normalized item needs at least one bounded source reference. Current
  source classes all have concrete provenance; providers must preserve it and
  must not invent placeholder references. If a future source class cannot
  provide provenance, its contract must define a narrow explicit exception.
- When a selection names entity references, returned entity references must be
  drawn from that exact set. A provider may return a subset of a multi-entity
  selection; related entities need an explicit future contract before they can
  be returned.
- Tool capabilities use the `tool_result` source class, and context-provider
  capabilities do not. Tool projections must use registered field names and
  leave unselected payload fields empty (`None`); both the adapter and shared
  coordinator reject populated unrequested fields.
- Optional source failures include the stable provider ID, operation, and
  bounded reason. The operation distinguishes failures when a provider supports
  multiple operations without copying request payloads into failure records.
- Provider deadlines are cooperative absolute monotonic deadlines. Providers
  must pass the remaining budget to blocking dependencies. The synchronous
  coordinator detects a non-cooperative overrun after the provider returns;
  it cannot hard-cancel that call. The profile adapter passes the effective
  deadline to Postgres, while the other built-in wrappers operate on already
  loaded snapshots.
- Payloads must be typed Pydantic models at construction and at the shared
  result boundary. External-research and client-context items cannot claim
  authoritative authority. Normalized items carry bounded field-sensitivity
  labels for their disclosed typed-payload fields; omitted labels inherit the
  conservative item-level classification, and the aggregate cannot be less
  restrictive than an explicit field label.
- [`applications/contracts.py`](../../backend/src/personal_ai/applications/contracts.py)
  and [`applications/registry.py`](../../backend/src/personal_ai/applications/registry.py)
  compose provider/tool registration metadata with `ApplicationDefinition` and
  the authenticated `RequestScope`. Registration alone does not authorize
  cross-app reads.
- [`context/assembler.py`](../../backend/src/personal_ai/context/assembler.py)
  accepts explicit `context_selections` and returns normalized `source_items`
  and bounded `source_failures` in `AssembledContext`. The Phase 11 boundary did
  not choose or inject sources. Phase 12 now fits explicitly prepared items into
  model messages through the shared builder; it still does not choose sources.
  See the [Phase 12 guide](phase-12-implementation-guide.md).

## Existing-source wrappers

[`context/adapters.py`](../../backend/src/personal_ai/context/adapters.py)
provides typed projections over existing request snapshots:

- conversation history uses only the active branch supplied to the wrapper and
  includes a summary only when it is compatible with that branch;
- memory returns selected active memory projections without exposing vectors or
  lifecycle internals, and reapplies the existing rejected-status and
  content-sensitivity checks at this disclosure seam. Lifecycle and source
  validation remain the retriever's responsibility;
- research evidence validates every referenced observation's owner, app,
  workspace, session, and accepted status before projecting its URL or
  fingerprint, and preserves evidence expiry;
- client context is non-authoritative and limited to selected request fields;
- tool results require an explicitly registered read-only capability with
  bounded fields and bytes, and remain read-only context.

Profile and client-context adapters preserve requested field order and emit no
more items than max_results. Conversation history reserves an item for a
compatible summary when it fits. Summary provenance is retained exactly up to
the bounded 200-reference contract; oversized provenance is skipped with a
bounded reason while valid recent history remains available. If the summary
and recent history exceed the response-byte allowance, the adapter trims older
history first and omits only a summary that cannot fit by itself.

These wrappers do not create domain database clients. Synthetic domain
providers in `backend/tests/test_context_sources.py` exercise the registration
and shared-preparation path with typed payloads and deterministic source refs.

## Owner-wide AI profile

The profile is a sparse AI-owned record, separate from inferred memory and
domain records. [`context/profile.py`](../../backend/src/personal_ai/context/profile.py)
defines the fixed field vocabulary, user-set provenance, per-field sharing,
and provider projection. The owner can manage it through `GET` and `PUT`
`/v1/profile`; the route is limited to the standalone `personal_ai` scope and
uses the verified owner principal in deployed configurations.
Applications receive only requested fields explicitly shared with their
application ID. No values are inferred or copied from domain records.
Profile storage unavailability and timeout return the stable `storage_unavailable`
response; an update revision conflict returns HTTP 409 with
`profile_update_conflict`.

[`persistence/postgres_context.py`](../../backend/src/personal_ai/persistence/postgres_context.py)
stores it in the canonical owner-wide `personal_ai` Postgres namespace with
revisioned updates and filtered sharing reads. Migration
[`015_global_profile.sql`](../../backend/src/personal_ai/persistence/migrations/015_global_profile.sql)
creates the bounded record family. The family is included in the shared
Postgres account export and deletion inventory. The provider returns shared
fields in request order and honors max_results; unshared and absent fields
remain absent.

## Scope limits

Phase 11 does not implement real Travel, Shopping, Finance, or Health context
providers, context-selection policy, model selection, cross-app federation, or
mutation tools. Provider results are not automatically added to model input.
The fixed `local` owner remains a local/test identity; deployment identity and
private API invocation remain subject to the open Phase 9 release gates.
