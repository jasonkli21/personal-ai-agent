# Phase 11 implementation evidence — Context source and provider abstraction

Date: 2026-10-07 (America/Los_Angeles)
Original implementation source: Phase 11 implementation based on clean
repository revision `bab6c429e2f7531cce70fec0493943b29107cfe0`.
Independent-review fixes were first tested in the review-fix working tree
based on `a00324fbfb51f432c7c8fe216c9a64e4f6e727b9`, then rerun on committed
revision `f574a8d1a52d4e86a6efe80fb1e9b177589ce305`, using the repository
Python 3.11.15 virtual environment. The exact-commit rerun is recorded below.

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
- Reviewed the root README for the original Phase 11 change and updated it to
  reflect the then-new user-visible profile and context-preparation capability.

## Independent review remediation

The 2026-10-07 independent review's twelve findings are addressed in the
existing provider, assembler, wrapper, and profile-repository seams:

- Research attribution now validates evidence/observation owner, application,
  workspace, session, accepted status, missing IDs, and duplicate IDs before
  projecting source URLs or fingerprints. Evidence expiry remains unchanged.
- Memory source preparation requires the typed retrieval result and reapplies
  the existing rejected-status and content policy before projection. Lifecycle
  and source validation remain with the retriever.
- Universal target and entity scope is checked across the complete plan before
  missing, disabled, or unsupported providers can become optional failures.
- The assembler deadline reaches the coordinator, caps each source deadline,
  and is checked before later source work and before successful return.
- Empty required output raises a stable preparation error and prevents later
  optional reads. Optional empty output remains a bounded advisory failure.
- Profile and client-context projections preserve requested order and honor
  result limits. Conversation summaries reserve a result slot, preserve exact
  provenance up to 200 references, and cannot discard valid history when a
  summary exceeds provenance or response-byte bounds.
- Runtime boundaries reject untyped payloads and authoritative claims from
  external research or client context. Field-sensitivity metadata is bounded,
  tied to payload fields, defaults to the item-level classification, and
  cannot understate the aggregate.
- Optional factory/validator timeout and dependency errors map to safe bounded
  failures; explicit preparation denials and identity invariants remain
  fail-closed.
- Opt-in Postgres profile repository tests now cover migration-backed CRUD,
  owner-wide storage and isolation, selective sharing/revocation, in-memory
  parity, concurrent initial and disjoint updates, revisions, deadlines, and
  exported user-set provenance.

## Checks

Original Phase 11 implementation checks:

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

## Independent review verification

- Exact tested source revision: `f574a8d1a52d4e86a6efe80fb1e9b177589ce305`.
- `make backend-test backend-lint`: **635 passed, 26 skipped; Ruff passed**.
  Skips include 23 Postgres/DynamoDB local-persistence cases, one cloud smoke
  case, and two manual provider/context cases.
- `make context-eval memory-eval research-eval domain-eval`: **passed** with
  deterministic offline/synthetic fixtures only.
- Focused context-source and local-persistence test files: **61 passed,
  23 skipped**.
- The root README was reviewed; the remediation changes validation and bounds
  without changing the user-visible capability, so no new README edit was
  needed.
- The Postgres profile contract tests are present but were skipped because
  `PERSISTENCE_TEST_POSTGRES_DSN` and DynamoDB Local were not configured.
- No Postgres migration/repository execution, cloud, provider, deployment, or
  browser acceptance is claimed. Fakes and offline evaluations do not establish
  those external behaviors.

The source fixes and local regression coverage are implemented and offline
verified. Local-engine and deployment acceptance remain open.

## Supplemental review remediation

The additive findings in the 2026-10-07 supplemental review are addressed in
the same provider, adapter, profile API, and status-document seams:

- All current source classes require at least one concrete bounded source
  reference. Construction and coordinator result validation reject missing
  provenance; no placeholder references are synthesized.
- Provider specs require tool capabilities to use `tool_result`, and reserve
  `tool_result` for tool capabilities. When a selection names entity references,
  returned references must be in that exact requested set.
- Tool projection validates the selected fields at the adapter and coordinator
  boundaries. The typed result keeps its schema, while any populated unrequested
  field is rejected.
- Provider deadlines are documented and tested as cooperative absolute
  monotonic deadlines. Blocking providers must propagate the budget; a
  non-cooperative synchronous call is detected after return and is not claimed
  to be hard-cancelled.
- Profile persistence unavailability and timeouts map to the stable storage
  unavailable response. Postgres statement and lock timeouts normalize to the
  timeout type at the database boundary. Exhausted profile insert retries and
  revision conflicts normalize to `PersistenceConflict`, which maps to HTTP 409
  with the safe `profile_update_conflict` code.
- Optional provider failures carry the bounded operation name alongside the
  provider ID and reason, and the coordinator verifies that it matches the
  selection.
- The documentation router and product requirements now state that Phase 11 is
  implemented locally and Phase 12 is next, while local-Postgres and cloud
  acceptance gates remain open.

### Supplemental review checks

- Tested source: base revision `3c300235cf2b46ea078be87af605b21995451574`
  plus the supplemental-remediation working-tree changes recorded here. Those
  changes were not committed when these checks ran.
- `backend/.venv/bin/python -m pytest`: **644 passed, 26 skipped**. Skips
  include the opt-in local persistence, cloud, and manual provider cases.
- `backend/.venv/bin/ruff check .`: **passed**.
- `backend/.venv/bin/python -m personal_ai.evaluation.context`: **passed**;
  deterministic offline fixtures only.
- Focused context-source, auth, and Postgres deadline tests: **85 passed**.
- `git diff --check`: **passed**.
- Local Postgres profile integration, cloud, provider, deployment, and browser
  behavior remain unverified. These checks do not establish those external
  behaviors.
