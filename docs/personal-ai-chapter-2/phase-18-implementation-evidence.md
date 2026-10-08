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
