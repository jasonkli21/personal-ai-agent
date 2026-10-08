# Phase 18 implementation evidence — Endpoint registry and strict-free admission

**Date:** 2026-10-08

**Tested revision:** working tree based on `d5fafc4` (`main`); Phase 18 changes described here were present during checks and are included in the implementation commit.

## Delivered

- Added immutable, bounded endpoint, counter-compatibility, provider data-use,
  quota-bucket, candidate-requirement, and registry-snapshot contracts in
  `backend/src/personal_ai/routing/contracts.py`.
- Added deterministic strict-free admission and candidate assessment in
  `backend/src/personal_ai/routing/registry.py`. It reports all configured
  profiles without scores, rejects profile sets above 32, requires known
  endpoint-specific bounds and operation-scoped quota membership, validates
  exact counter and structured-schema compatibility when requested, and
  revalidates candidate registry versions before dispatch.
- Added configured Gemini generation/embedding and optional Groq/Cloudflare
  profiles in `backend/src/personal_ai/routing/configured.py`. Operator facts
  default to unknown or disabled; profiles store symbolic credential references
  only. No current provider quota values are hard-coded.
- Added the Phase 10-owned Postgres registry snapshot migration and a
  compare-and-swap repository in
  `backend/src/personal_ai/persistence/migrations/016_endpoint_registry.sql`
  and `backend/src/personal_ai/persistence/postgres_routing.py`.
- Added Phase 18 contract, lifecycle, configuration, and repository tests, plus
  the [implementation guide](phase-18-implementation-guide.md). The root README
  now describes the internal registry; application workflows remain Gemini-only.

## Verification

Commands ran from the repository root unless stated otherwise:

| Check | Result |
| --- | --- |
| `cd backend && .venv/bin/python -m pytest -q tests/test_endpoint_registry.py tests/test_postgres_routing.py tests/test_settings.py` | **Passed:** 47 tests |
| `cd backend && .venv/bin/python -m ruff check .` | **Passed** |
| `cd backend && UV_CACHE_DIR=/tmp/personal-ai-phase18-uv-cache uv build --no-build-isolation` | **Passed:** source distribution and wheel built |
| `git diff --check` | **Passed** |
| `cd backend && .venv/bin/python -m pytest -q` | **857 passed, 26 skipped, 2 failed** |

The two full-suite failures are in unchanged `backend/tests/test_context_sources.py`:
`test_registered_synthetic_application_uses_shared_preparation_without_app_branching`
and `test_assembler_rechecks_grants_and_injects_typed_source_with_actual_manifest`.
Both use a fixed `NOW` of 2026-10-07 with source evidence expiring one day later;
the run on 2026-10-08 observes the item as `expired`. This date-sensitive fixture
failure is unrelated to the Phase 18 files. The run also emitted the existing
Starlette/httpx deprecation warning.

## Configuration and remaining gates

Strict-free, tier, privacy, count-compatibility, structured-output, and quota
attestations default off or unknown. Model context/output limits are unset by
default; admission fails closed where a task requires an unknown bound. The
Gemini embedding profile is separately represented and unverified. Groq and
Cloudflare profiles do not claim authoritative token counting. No profile is
enabled for automatic use solely because of its provider name.

The registry candidate API is not wired into chat, research, memory, or other
request workflows; provider selection remains Gemini-only pending the later
semantic-routing phase. Migration `016_endpoint_registry.sql` was not applied to
a database. No live provider, account/tier, privacy, quota, deployment, or
cloud-security preflight was performed. Those behaviors remain unverified.

## Independent review follow-up — 2026-10-08

**Tested revision:** working tree based on `5ed69928804203c5f96bbe5b795b22a22fc571a2`, including the review-follow-up changes below.

The review findings were addressed in the Phase 18 registry boundary:

- Candidate generation and revalidation reload the durable snapshot. Candidate
  sets retain their original requirements, cannot select a profile rejected in
  the frozen assessment, and cannot be revalidated under weaker requirements.
- Required operation facts are explicit. Missing generation bounds, count
  requirements, embedding dimensions, search bounds, or an empty capability
  set fail validation; explicit zero bounds remain valid.
- Operator configuration reconciles against the durable desired set. Built-in
  profile IDs remain stable across model/account/credential changes, changed
  facts advance profile versions, removed profiles remain versioned in a
  durable high-water table, and conflicting concurrent reconciliation fails
  with a registry-level conflict.
- Strict-free and verified quota assertions carry bounded, scoped evidence
  references. Credential source/reference pairs are checked, expired
  attestations and known quota exhaustion fail admission, and registry/repository
  boundaries revalidate Pydantic instances.
- First-row creation uses a conflict-safe insert/reload path. Registry payloads
  have a 128 KiB compact-JSON bound before database writes, below migration 016's
  256 KiB JSONB check.

The independent pass also rejected operationless requirements and covered
attestation expiration. No Phase 19/21 routing strategy or workflow dispatch was
added.

### Verification

| Check | Result |
| --- | --- |
| `cd backend && .venv/bin/python -m pytest -q tests/test_endpoint_registry.py tests/test_postgres_routing.py tests/test_settings.py tests/test_litellm_gateway.py` | **Passed:** 152 tests; one existing Pydantic `ReadOnly` warning |
| `cd backend && .venv/bin/python -m pytest -q` | **895 passed, 26 skipped, 2 failed**; the same unrelated date-sensitive `tests/test_context_sources.py` failures listed above |
| `cd backend && .venv/bin/python -m ruff check .` | **Passed** |
| `cd backend && UV_CACHE_DIR=/tmp/personal-ai-phase18-review-uv-cache uv build --no-build-isolation` | **Passed:** source distribution and wheel built |
| `git diff --check` | **Passed** |
| Postgres integration | **Not run:** Docker is unavailable in this environment; repository contract tests use the in-memory fixture |

Migration 016 was not applied to a database. Cross-process behavior is covered
by two registry instances over the shared repository fixture, not by a live
Postgres run. Account/tier/privacy/quota attestations and live provider behavior
remain unverified.
