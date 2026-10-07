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
  registered capabilities and validates the full selection set before any
  provider fetch. Owner/app/workspace scope, operation fields, time windows,
  result count, response bytes, timeout allowance, and read-only tool
  registration are checked at admission.
- [`applications/contracts.py`](../../backend/src/personal_ai/applications/contracts.py)
  and [`applications/registry.py`](../../backend/src/personal_ai/applications/registry.py)
  compose provider/tool registration metadata with `ApplicationDefinition` and
  the authenticated `RequestScope`. Registration alone does not authorize
  cross-app reads.
- [`context/assembler.py`](../../backend/src/personal_ai/context/assembler.py)
  accepts explicit `context_selections` and returns normalized `source_items`
  and bounded `source_failures` in `AssembledContext`. It does not choose
  sources or inject these items into model messages; those belong to Phase 12
  and later planning work.

## Existing-source wrappers

[`context/adapters.py`](../../backend/src/personal_ai/context/adapters.py)
provides typed projections over existing request snapshots:

- conversation history uses only the active branch supplied to the wrapper and
  includes a summary only when it is compatible with that branch;
- memory returns selected active memory projections without exposing vectors or
  lifecycle internals;
- research evidence preserves observation IDs, URLs, fingerprints, and expiry;
- client context is non-authoritative and limited to selected request fields;
- tool results require an explicitly registered read-only capability with
  bounded fields and bytes, and remain read-only context.

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

[`persistence/postgres_context.py`](../../backend/src/personal_ai/persistence/postgres_context.py)
stores it in the canonical owner-wide `personal_ai` Postgres namespace with
revisioned updates and filtered sharing reads. Migration
[`015_global_profile.sql`](../../backend/src/personal_ai/persistence/migrations/015_global_profile.sql)
creates the bounded record family. The family is included in the shared
Postgres account export and deletion inventory.

## Scope limits

Phase 11 does not implement real Travel, Shopping, Finance, or Health context
providers, context-selection policy, model selection, cross-app federation, or
mutation tools. Provider results are not automatically added to model input.
The fixed `local` owner remains a local/test identity; deployment identity and
private API invocation remain subject to the open Phase 9 release gates.
