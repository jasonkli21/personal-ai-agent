# Phase 11 implementation evidence — Context source and provider abstraction

Date: 2026-10-07 (America/Los_Angeles)
Tested source tree: Phase 11 implementation based on clean repository revision
`bab6c429e2f7531cce70fec0493943b29107cfe0`. Backend checks used the repository
Python 3.11.15 virtual environment. The implementation commit includes the
source and documentation changes described here.

## Delivered

- Added typed source classes, normalized context items with domain-typed
  payloads, provider operation specifications, bounded selections/results,
  provenance, permission dependencies, and fail-closed provider admission.
- Extended application capability registration for shared context providers
  and bounded read-only tool results. `ContextAssembler` can prepare explicit
  selections and expose their normalized items/failures to the next builder
  phase.
- Added wrappers for active-branch conversation/compatible summaries,
  retrieved memory projections, immutable research evidence, client context,
  and registered read-only tool results. Synthetic application fixtures verify
  app registration through shared preparation without app-specific branching.
- Added sparse owner-wide AI profile defaults for units, locale, response style,
  and answer length. Updates retain user-set provenance and per-field app
  sharing; `GET`/`PUT /v1/profile` require the owner principal and standalone
  `personal_ai` scope. A Postgres repository and migration persist the profile,
  and the record family is in account export/deletion inventory.
- Reviewed the root README and updated it to reflect the new user-visible
  profile and context-preparation capability.

## Checks

- `backend/.venv/bin/python -m pytest`: **590 passed, 25 skipped**. Skips were
  22 local Postgres/DynamoDB integration cases, one cloud smoke case, and two
  manual provider/context cases. They do not establish local-engine or cloud
  behavior.
- `backend/.venv/bin/ruff check .`: **passed**.
- `backend/.venv/bin/python -m personal_ai.evaluation.context`: **passed**;
  deterministic synthetic fixtures.
- `backend/.venv/bin/python -m personal_ai.evaluation.memory`: **passed**;
  deterministic synthetic fixtures.
- `backend/.venv/bin/python -m personal_ai.evaluation.research`: **passed**;
  deterministic synthetic fixtures.
- `backend/.venv/bin/python -m personal_ai.evaluation.domain`: **passed**;
  synthetic Travel and Shopping fixtures.
- `git diff --check`: **passed**.

The local persistence integration suite was not configured, so migration
`015_global_profile.sql` and the Postgres profile repository were not exercised
against a running database. Provider evaluations used fakes and do not prove
external provider behavior.

## Remaining boundaries and verification

- Phase 11 source preparation requires explicit selections. It does not choose
  sources or add the prepared items to model messages; Phase 12 owns the
  context builder integration.
- No real domain database provider, cross-app federation, sensitivity policy,
  or mutation tool was added. Those remain later-phase scope.
- Run the local Postgres/DynamoDB integration suite on a host with the required
  endpoints, including a migration and profile CRUD/export check.
- Production authentication, private API invocation, Neon/AWS/GCP behavior,
  provider rights, and deployment security remain open under the Phase 9/10
  release gates. Fakes do not establish those behaviors.

Phase 11 typed provider preparation and synthetic acceptance are implemented
locally. Database and deployment acceptance remain unverified.
